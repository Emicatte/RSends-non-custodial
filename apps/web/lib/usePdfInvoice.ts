/**
 * usePdfInvoice — generatore PDF della fattura aggregata delle commissioni (Step 3).
 *
 * Riusa lo stile del PDF ricevuta ridisegnato (lib/usePdfReceipt.ts): jsPDF,
 * palette chiara brand (terracotta), font Helvetica/Courier. NON dipende da
 * usePdfReceipt (la palette è replicata qui per non modificare il file ricevuta).
 *
 * `buildInvoiceDoc(p)` ritorna l'istanza jsPDF (sync, niente QR) così è usabile
 * sia nel browser (`generatePdfInvoice` → doc.save) sia in Node (doc.output).
 *
 * IVA/regime sono PARAMETRICI: se i campi tax_* sono assenti si mostra "—",
 * mai un valore fiscale inventato. Emittente placeholder finché non reale.
 */

import jsPDF from 'jspdf'

export interface InvoiceClientSnapshot {
  owner_address?: string | null
  billing_legal_name?: string | null
  billing_vat_number?: string | null
  billing_tax_code?: string | null
  billing_address_line?: string | null
  billing_city?: string | null
  billing_postal_code?: string | null
  billing_country?: string | null
  billing_email?: string | null
  billing_pec?: string | null
}

export interface InvoiceIssuerSnapshot {
  legal_name?: string | null
  vat_number?: string | null
  address?: string | null
  country?: string | null
  email?: string | null
}

export interface InvoicePdfData {
  invoice_number: string
  status: string                 // draft | issued
  created_at: string
  issued_at?: string | null
  period_start: string
  period_end: string
  tx_count: number
  unit_price_eur: string         // Decimal as string ("0.01...")
  subtotal_eur: string
  tax_regime?: string | null
  tax_rate?: string | null
  tax_amount_eur?: string | null
  tax_note?: string | null
  total_eur: string
  snapshot_issuer?: InvoiceIssuerSnapshot | null
  snapshot_client?: InvoiceClientSnapshot | null
}

// Palette brand chiara — identica a usePdfReceipt.ts.
const C = {
  paper:      [250, 250, 250] as [number, number, number],
  ink:        [10,  10,  10 ] as [number, number, number],
  ink55:      [120, 120, 120] as [number, number, number],
  ink40:      [160, 160, 160] as [number, number, number],
  ink12:      [225, 225, 225] as [number, number, number],
  terracotta: [200, 81,  44 ] as [number, number, number],
  wash:       [245, 232, 224] as [number, number, number],
  warn:       [180, 95,  20 ] as [number, number, number],
  warnBg:     [250, 240, 225] as [number, number, number],
  white:      [255, 255, 255] as [number, number, number],
}

// Scarta placeholder/vuoti (es. "IT______", "[EMITTENTE — DATI DA CONFIGURARE]").
const real = (v?: string | null): string => {
  const s = (v || '').trim()
  if (!s) return ''
  if (s.includes('___') || /configurare/i.test(s)) return ''
  return s
}

const fmtEur = (v?: string | null): string => {
  const n = parseFloat(v || '0')
  return n.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const fmtDate = (v?: string | null): string => {
  if (!v) return '—'
  try {
    return new Date(v).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' })
  } catch {
    return v
  }
}

export function buildInvoiceDoc(p: InvoicePdfData): jsPDF {
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const W = 210, H = 297, ml = 18, mr = 18
  const contentW = W - ml - mr

  const issuer = p.snapshot_issuer || {}
  const client = p.snapshot_client || {}

  const emiName = real(issuer.legal_name) || '[EMITTENTE — DATI DA CONFIGURARE]'
  // TODO(legal): RPagos S.R.L. (Costa Rica) — sostituire con dati reali emittente.
  const emiParts = [
    real(issuer.address),
    real(issuer.vat_number) ? `VAT ${real(issuer.vat_number)}` : '',
    real(issuer.country),
    real(issuer.email),
  ].filter(Boolean)

  const cliName = real(client.billing_legal_name)
  const cliVat = real(client.billing_vat_number)
  const clientIncomplete = !(cliName && cliVat)

  // ── Sfondo + accento terracotta ──
  doc.setFillColor(...C.paper)
  doc.rect(0, 0, W, H, 'F')
  doc.setFillColor(...C.terracotta)
  doc.rect(0, 0, W, 1.2, 'F')

  // ── Header ──
  doc.setTextColor(...C.ink)
  doc.setFontSize(24)
  doc.setFont('helvetica', 'bold')
  doc.text('RSends', ml, 18)

  doc.setTextColor(...C.ink55)
  doc.setFontSize(7)
  doc.setFont('helvetica', 'normal')
  doc.text('Gateway di Pagamento B2B Multi-chain', ml, 23)

  doc.setTextColor(...C.ink55)
  doc.setFontSize(6.5)
  doc.setFont('helvetica', 'bold')
  doc.text(emiName, ml, 29)
  if (emiParts.length) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6)
    doc.text(emiParts.join('  ·  '), ml, 33)
  }

  // Badge stato (draft tenue / issued terracotta)
  const isIssued = (p.status || '').toLowerCase() === 'issued'
  const badgeW = 30, badgeH = 9, badgeX = W - mr - badgeW, badgeY = 13
  doc.setFillColor(...(isIssued ? C.wash : C.ink12))
  doc.roundedRect(badgeX, badgeY, badgeW, badgeH, 2, 2, 'F')
  doc.setTextColor(...(isIssued ? C.terracotta : C.ink55))
  doc.setFontSize(7.5)
  doc.setFont('helvetica', 'bold')
  doc.text(isIssued ? 'EMESSA' : 'BOZZA', badgeX + badgeW / 2, badgeY + 5.8, { align: 'center' })

  // ── Titolo documento ──
  doc.setTextColor(...C.terracotta)
  doc.setFontSize(15)
  doc.setFont('helvetica', 'bold')
  doc.text('Fattura — Commissioni Gateway', ml, 44)

  doc.setTextColor(...C.ink55)
  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.text(`N. ${p.invoice_number}`, ml, 49)

  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.line(ml, 53, W - mr, 53)

  let y = 58

  // ── Riga meta: numero · data · periodo ──
  const metaH = 15
  doc.setFillColor(...C.white)
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.roundedRect(ml, y, contentW, metaH, 2, 2, 'FD')

  const dataEmis = isIssued ? fmtDate(p.issued_at) : fmtDate(p.created_at)
  const metaCols = [
    { label: 'NUMERO', value: p.invoice_number },
    { label: isIssued ? 'DATA EMISSIONE' : 'DATA (BOZZA)', value: dataEmis },
    { label: 'PERIODO', value: `${fmtDate(p.period_start)} – ${fmtDate(p.period_end)}` },
  ]
  const colW = contentW / metaCols.length
  metaCols.forEach(({ label, value }, i) => {
    const x = ml + 6 + i * colW
    doc.setTextColor(...C.ink55)
    doc.setFontSize(6)
    doc.setFont('courier', 'bold')
    doc.text(label, x, y + 6)
    doc.setTextColor(...C.ink)
    doc.setFontSize(7)
    doc.setFont('courier', 'normal')
    doc.text(value, x, y + 11)
  })
  y += metaH + 7

  // ── Prestatore / Cliente (due colonne) ──
  const colGap = 8
  const halfW = (contentW - colGap) / 2

  const blockTitle = (txt: string, x: number) => {
    doc.setTextColor(...C.ink55)
    doc.setFontSize(6.5)
    doc.setFont('helvetica', 'bold')
    doc.text(txt, x, y)
  }
  blockTitle('PRESTATORE', ml)
  blockTitle('CLIENTE', ml + halfW + colGap)

  doc.setFontSize(7.5)
  // Prestatore
  let py = y + 5
  doc.setTextColor(...C.ink)
  doc.setFont('helvetica', 'bold')
  doc.text(emiName, ml, py)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6.5)
  emiParts.forEach((line) => { py += 4; doc.text(line, ml, py) })

  // Cliente
  const cx = ml + halfW + colGap
  let cy = y + 5
  doc.setFontSize(7.5)
  if (cliName) {
    doc.setTextColor(...C.ink)
    doc.setFont('helvetica', 'bold')
    doc.text(cliName, cx, cy)
  } else {
    doc.setTextColor(...C.ink40)
    doc.setFont('helvetica', 'italic')
    doc.text('— ragione sociale mancante —', cx, cy)
  }
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6.5)
  const cliLines = [
    cliVat ? `VAT/P.IVA ${cliVat}` : '',
    real(client.billing_tax_code) ? `CF ${real(client.billing_tax_code)}` : '',
    real(client.billing_address_line),
    [real(client.billing_postal_code), real(client.billing_city), real(client.billing_country)].filter(Boolean).join(' '),
    real(client.billing_email),
    real(client.billing_pec) ? `PEC ${real(client.billing_pec)}` : '',
    real(client.owner_address) ? `Wallet ${real(client.owner_address)}` : '',
  ].filter(Boolean)
  cliLines.forEach((line) => { cy += 4; doc.text(line, cx, cy) })

  y = Math.max(py, cy) + 8

  // ── Banner anagrafica cliente incompleta (resta BOZZA) ──
  if (clientIncomplete) {
    const bh = 11
    doc.setFillColor(...C.warnBg)
    doc.roundedRect(ml, y, contentW, bh, 2, 2, 'F')
    doc.setTextColor(...C.warn)
    doc.setFontSize(7)
    doc.setFont('helvetica', 'bold')
    doc.text('Anagrafica cliente incompleta', ml + 5, y + 4.5)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6)
    doc.text(
      'Mancano ragione sociale e/o VAT: la fattura resta in BOZZA e non può essere emessa.',
      ml + 5, y + 8.5,
    )
    y += bh + 6
  }

  // ── Tabella riga servizio ──
  // Intestazione
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.setFillColor(...C.wash)
  doc.rect(ml, y, contentW, 7, 'F')
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6)
  doc.setFont('helvetica', 'bold')
  doc.text('DESCRIZIONE', ml + 2, y + 4.6)
  doc.text('Q.TÀ', ml + contentW * 0.62, y + 4.6, { align: 'right' })
  doc.text('PREZZO UNIT.', ml + contentW * 0.80, y + 4.6, { align: 'right' })
  doc.text('IMPORTO', W - mr - 2, y + 4.6, { align: 'right' })
  y += 7

  // Riga
  const descLines = doc.splitTextToSize(
    'Servizi di processing e settlement pagamenti blockchain — commissione gateway (€0,01/transazione)',
    contentW * 0.58,
  )
  const rowH = Math.max(11, 4 + descLines.length * 3.6)
  doc.setTextColor(...C.ink)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7)
  doc.text(descLines, ml + 2, y + 4.5)
  doc.setFont('courier', 'normal')
  doc.setFontSize(7.5)
  doc.text(String(p.tx_count), ml + contentW * 0.62, y + 4.5, { align: 'right' })
  doc.text(`€ ${fmtEur(p.unit_price_eur)}`, ml + contentW * 0.80, y + 4.5, { align: 'right' })
  doc.text(`€ ${fmtEur(p.subtotal_eur)}`, W - mr - 2, y + 4.5, { align: 'right' })
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.2)
  doc.line(ml, y + rowH, W - mr, y + rowH)
  y += rowH + 6

  // ── Blocco IVA/TOTALI parametrico ──
  const rate = real(p.tax_rate)
  const taxAmt = real(p.tax_amount_eur)
  const regime = real(p.tax_regime)
  const totRows: Array<[string, string]> = [
    ['Imponibile', `€ ${fmtEur(p.subtotal_eur)}`],
    ['Aliquota IVA', rate ? `${rate}%` : '—'],
    ['IVA', taxAmt ? `€ ${fmtEur(taxAmt)}` : '—'],
  ]
  const boxW = 78
  const boxX = W - mr - boxW
  totRows.forEach(([label, value], i) => {
    const ry = y + i * 6
    doc.setTextColor(...C.ink55)
    doc.setFontSize(7)
    doc.setFont('helvetica', 'normal')
    doc.text(label, boxX, ry + 4)
    doc.setTextColor(...C.ink)
    doc.setFont('courier', 'normal')
    doc.text(value, W - mr - 2, ry + 4, { align: 'right' })
  })
  let ty = y + totRows.length * 6 + 1
  // Totale evidenziato
  doc.setDrawColor(...C.terracotta)
  doc.setLineWidth(0.4)
  doc.line(boxX, ty, W - mr, ty)
  ty += 6
  doc.setTextColor(...C.terracotta)
  doc.setFontSize(9)
  doc.setFont('helvetica', 'bold')
  doc.text('TOTALE', boxX, ty)
  doc.setTextColor(...C.ink)
  doc.setFontSize(11)
  doc.text(`€ ${fmtEur(p.total_eur)}`, W - mr - 2, ty, { align: 'right' })

  // Nota regime IVA (parametrica)
  let ny = y
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6.5)
  doc.setFont('helvetica', 'normal')
  const regimeLine = regime || 'Regime IVA: da definire'
  doc.text(regimeLine, ml, ny + 4)
  if (real(p.tax_note)) {
    const noteLines = doc.splitTextToSize(real(p.tax_note), boxX - ml - 4)
    doc.text(noteLines, ml, ny + 9)
  } else {
    doc.setTextColor(...C.ink40)
    doc.setFontSize(5.8)
    // TODO(legal): regime IVA RPagos CR→cliente da definire (reverse charge / art.7-ter?).
    doc.text('IVA/regime parametrici — nessun valore fiscale applicato in attesa di definizione.', ml, ny + 9)
  }

  // ── Footer legale parametrico ──
  const fy = H - 20
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.line(ml, fy, W - mr, fy)
  doc.setTextColor(...C.ink40)
  doc.setFontSize(5.5)
  doc.setFont('helvetica', 'normal')
  doc.text(
    'Documento generato da RSends. Dati emittente e regime IVA in attesa di configurazione legale. '
    + 'Importi in EUR. Questo documento non sostituisce la fattura fiscale definitiva finché non emesso.',
    ml, fy + 5, { maxWidth: contentW },
  )

  return doc
}

export function generatePdfInvoice(p: InvoicePdfData): void {
  const doc = buildInvoiceDoc(p)
  const safe = (p.invoice_number || 'fattura').replace(/[^A-Za-z0-9_-]/g, '_')
  doc.save(`RSends_${safe}.pdf`)
}
