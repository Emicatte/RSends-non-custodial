"""
RPagos Backend Core — Analizzatore di Anomalie.

Come nella radioastronomia, cerchiamo "segnali" nel rumore:
  - Volume spike: picchi nel numero di TX/ora (come un burst radio FRB)
  - Amount outlier: importi fuori dalla distribuzione normale (come una stella variabile)
  - Frequency burst: raffica di TX in un breve intervallo (possibile attacco replay)

Usa z-score (deviazioni standard dalla media) per identificare outlier.
Scipy.stats fornisce i test statistici, Pandas la manipolazione temporale.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db_models import TransactionLog, AnomalyAlert, AnomalyType
from app.models.schemas import AnomalyAlertResponse, AnomalyReportResponse


async def analyze_transactions(
    db: AsyncSession,
    window_hours: int = 24,
    currency_filter: Optional[str] = None,
) -> AnomalyReportResponse:
    """
    Analisi completa delle transazioni nelle ultime `window_hours` ore.

    Restituisce un report con tutte le anomalie trovate.
    Simile a come un astronomo analizza un segnale:
      1. Raccogli i dati (osservazione)
      2. Calcola la baseline (media + deviazione standard)
      3. Trova i picchi (z-score > soglia)
      4. Classifica le anomalie
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    # ── 1. Raccolta dati ─────────────────────────────────────
    query = select(TransactionLog).where(
        TransactionLog.tx_timestamp >= window_start
    )
    if currency_filter:
        query = query.where(TransactionLog.currency == currency_filter)
    query = query.order_by(TransactionLog.tx_timestamp)

    result = await db.execute(query)
    transactions = result.scalars().all()

    total = len(transactions)
    alerts: list[AnomalyAlertResponse] = []

    if total < settings.anomaly_min_sample_size:
        return AnomalyReportResponse(
            total_transactions=total,
            anomalies_found=0,
            alerts=[],
            analysis_window_hours=window_hours,
        )

    # ── 2. Converti in DataFrame per analisi ─────────────────
    df = pd.DataFrame([
        {
            "id": tx.id,
            "amount": tx.gross_amount,
            "eur_value": tx.eur_value or 0,
            "timestamp": tx.tx_timestamp,
            "currency": tx.currency,
        }
        for tx in transactions
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp")

    # ── 3. Analisi Volume (TX per ora) ───────────────────────
    # Come contare i fotoni per intervallo temporale in astrofisica
    df["hour_bucket"] = df["timestamp"].dt.floor("h")
    hourly_counts = df.groupby("hour_bucket").size()

    if len(hourly_counts) >= 3:
        z_scores = stats.zscore(hourly_counts.values.astype(float))
        threshold = settings.anomaly_z_score_threshold

        for i, (hour, count) in enumerate(hourly_counts.items()):
            if abs(z_scores[i]) > threshold:
                alert = AnomalyAlertResponse(
                    anomaly_type=AnomalyType.volume_spike.value,
                    z_score=round(float(z_scores[i]), 2),
                    description=(
                        f"Picco volume: {count} TX nell'ora {hour}. "
                        f"Media: {hourly_counts.mean():.1f} TX/h, "
                        f"z-score: {z_scores[i]:.2f} "
                        f"(soglia: ±{threshold}). "
                        f"Come un Fast Radio Burst nel traffico!"
                    ),
                    window_start=pd.Timestamp(hour).to_pydatetime(),
                    window_end=(pd.Timestamp(hour) + pd.Timedelta(hours=1)).to_pydatetime(),
                    affected_tx_count=int(count),
                )
                alerts.append(alert)

    # ── 4. Analisi Importi (outlier) ─────────────────────────
    # Come cercare stelle con luminosità anomala
    amounts = df["amount"].values
    if len(amounts) >= 3:
        z_amounts = stats.zscore(amounts)
        threshold = settings.anomaly_z_score_threshold

        outlier_mask = np.abs(z_amounts) > threshold
        if outlier_mask.any():
            outlier_df = df[outlier_mask]
            alert = AnomalyAlertResponse(
                anomaly_type=AnomalyType.amount_outlier.value,
                z_score=round(float(np.max(np.abs(z_amounts[outlier_mask]))), 2),
                description=(
                    f"Trovati {outlier_mask.sum()} importi anomali. "
                    f"Media: {amounts.mean():.2f}, σ: {amounts.std():.2f}. "
                    f"Range outlier: {outlier_df['amount'].min():.2f} – "
                    f"{outlier_df['amount'].max():.2f}. "
                    f"Come trovare una supernova nel campo!"
                ),
                window_start=window_start,
                window_end=now,
                affected_tx_count=int(outlier_mask.sum()),
            )
            alerts.append(alert)

    # ── 5. Analisi Frequenza (burst detection) ───────────────
    # Calcola gli intervalli tra TX consecutive (come il periodo di una pulsar)
    if len(df) >= 5:
        intervals = df["timestamp"].diff().dt.total_seconds().dropna().values
        if len(intervals) >= 3 and np.std(intervals) > 0:
            z_intervals = stats.zscore(intervals)
            # Intervalli molto brevi → z-score molto negativo
            burst_mask = z_intervals < -settings.anomaly_z_score_threshold
            if burst_mask.any():
                burst_count = int(burst_mask.sum())
                min_interval = float(intervals[burst_mask].min())
                alert = AnomalyAlertResponse(
                    anomaly_type=AnomalyType.frequency_burst.value,
                    z_score=round(float(np.min(z_intervals[burst_mask])), 2),
                    description=(
                        f"Rilevato burst: {burst_count} TX con intervallo anomalo. "
                        f"Intervallo minimo: {min_interval:.1f}s "
                        f"(media: {np.mean(intervals):.1f}s). "
                        f"Possibile replay attack o errore nel frontend. "
                        f"Come una pulsar millisecondo!"
                    ),
                    window_start=window_start,
                    window_end=now,
                    affected_tx_count=burst_count,
                )
                alerts.append(alert)

    # ── 6. Salva le anomalie nel DB ──────────────────────────
    for alert in alerts:
        db_alert = AnomalyAlert(
            anomaly_type=AnomalyType(alert.anomaly_type),
            z_score=alert.z_score,
            description=alert.description,
            window_start=alert.window_start,
            window_end=alert.window_end,
            affected_tx_count=alert.affected_tx_count,
        )
        db.add(db_alert)

    if alerts:
        await db.commit()

    return AnomalyReportResponse(
        total_transactions=total,
        anomalies_found=len(alerts),
        alerts=alerts,
        analysis_window_hours=window_hours,
    )
