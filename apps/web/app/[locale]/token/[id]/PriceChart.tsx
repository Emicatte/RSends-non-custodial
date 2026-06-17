'use client';

import { useEffect, useRef } from 'react';
import { createChart, ColorType, LineStyle } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts';

type Props = {
  history: { prices: [number, number][] } | null;
  range: string;
};

export default function PriceChart({ history, range }: Props) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current || !history?.prices) return;
    if (history.prices.length === 0) return;

    const positive =
      history.prices.length > 1 &&
      history.prices[history.prices.length - 1][1] >= history.prices[0][1];
    const color = positive ? '#0E9F6E' : '#D4342E';

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#FFFFFF' },
        textColor: '#0A0A0A',
        fontFamily: 'inherit',
      },
      grid: {
        vertLines: { color: 'rgba(10,10,10,0.04)' },
        horzLines: { color: 'rgba(10,10,10,0.04)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(10,10,10,0.08)',
      },
      timeScale: {
        borderColor: 'rgba(10,10,10,0.08)',
        timeVisible: range === '1',
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      crosshair: {
        mode: 1,
        vertLine: { color: 'rgba(10,10,10,0.3)', style: LineStyle.Dashed, width: 1 },
        horzLine: { color: 'rgba(10,10,10,0.3)', style: LineStyle.Dashed, width: 1 },
      },
    });

    const series = chart.addAreaSeries({
      lineColor: color,
      topColor: color + '40',
      bottomColor: color + '00',
      lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    series.setData(
      history.prices.map(([t, v]) => ({
        time: Math.floor(t / 1000) as UTCTimestamp,
        value: v,
      }))
    );

    chart.timeScale().fitContent();

    chartRef.current = chart;
    seriesRef.current = series;

    const onResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      try {
        chart.remove();
      } catch {
        // già disposed in Strict Mode, ignora
      }
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [history, range]);

  return <div ref={chartContainerRef} style={{ width: '100%', height: 400 }} />;
}
