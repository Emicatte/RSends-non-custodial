'use client';

import { useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useCoinGecko } from '@/hooks/useCoinGecko';
import AnimatedNumber from '@/components/motion/AnimatedNumber';
import { Link } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';

type Token = {
  id: string;
  symbol: string;
  name: string;
  image: string;
  current_price: number;
  price_change_percentage_24h: number;
  price_change_percentage_7d_in_currency?: number;
  sparkline_in_7d: { price: number[] };
  market_cap: number;
  total_volume: number;
  market_cap_rank: number;
};

type SortKey =
  | 'market_cap_rank'
  | 'current_price'
  | 'price_change_percentage_24h'
  | 'price_change_percentage_7d_in_currency'
  | 'total_volume'
  | 'market_cap';

function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 100;
  const h = 28;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(' ');
  return (
    <svg width={w} height={h} className="block">
      <polyline
        fill="none"
        stroke={positive ? '#0E9F6E' : '#D4342E'}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

function formatCompact(n: number): string {
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function formatPrice(n: number): string {
  const decimals = n < 1 ? 4 : 2;
  return '$' + n.toFixed(decimals);
}

export default function MarketsClient() {
  const t = useTranslations('markets');
  const sp = useSearchParams();
  const chainHint = sp.get('chain');
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('market_cap_rank');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const perPage = 100;
  const url = `/api/market/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=${perPage}&page=${page}&sparkline=true&price_change_percentage=24h,7d`;

  const { data: tokens, error, stale, loading } = useCoinGecko<Token[]>(
    url,
    `markets_p${page}`,
    { ttlMs: 30_000, refreshIntervalMs: 30_000 }
  );

  const filtered = useMemo(() => {
    if (!tokens) return [];
    const q = query.toLowerCase().trim();
    const list = q
      ? tokens.filter(
          (t) =>
            t.name.toLowerCase().includes(q) ||
            t.symbol.toLowerCase().includes(q)
        )
      : tokens;

    const sorted = [...list].sort((a, b) => {
      const av = (a[sortKey] ?? 0) as number;
      const bv = (b[sortKey] ?? 0) as number;
      return sortDir === 'asc' ? av - bv : bv - av;
    });
    return sorted;
  }, [tokens, query, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'market_cap_rank' ? 'asc' : 'desc');
    }
  };

  const SortHeader = ({
    label,
    k,
    align = 'left',
  }: {
    label: string;
    k: SortKey;
    align?: 'left' | 'right';
  }) => (
    <th
      onClick={() => toggleSort(k)}
      className={`text-xs tracking-[0.12em] text-[#0A0A0A]/60 font-medium py-4 px-4 uppercase cursor-pointer hover:text-[#0A0A0A] transition-colors select-none ${
        align === 'right' ? 'text-right' : 'text-left'
      }`}
    >
      {label}
      {sortKey === k && (
        <span className="ml-1 text-[#C8512C]">
          {sortDir === 'asc' ? '↑' : '↓'}
        </span>
      )}
    </th>
  );

  return (
    <main className="min-h-screen py-20">
      <div className="mx-auto max-w-[1440px] px-24">

        {/* Breadcrumb */}
        <nav className="mb-8 text-sm" aria-label="Breadcrumb">
          <ol className="flex items-center gap-2 text-[#0A0A0A]/60">
            <li>
              <Link href="/" className="hover:text-[#C8512C] transition-colors">
                Home
              </Link>
            </li>
            <li className="text-[#0A0A0A]/30">/</li>
            <li className="text-[#0A0A0A] font-medium">Markets</li>
          </ol>
        </nav>

        {/* Header */}
        <div className="mb-12">
          <p className="text-sm tracking-[0.18em] text-[#C8512C] font-medium mb-6">
            MARKETS
          </p>
          <h1 className="text-[72px] leading-[1.05] tracking-[-0.02em] font-semibold text-[#0A0A0A] mb-4">
            {t('pageTitle')}
          </h1>
          <p className="text-xl text-[#0A0A0A]/70 max-w-[680px]">
            {t('pageSubtitle')}
          </p>
        </div>

        {/* Chain hint chip (from landing carousel deep-link) */}
        {chainHint && (
          <div className="mb-6 flex items-center gap-2 text-sm">
            <span className="text-[#0A0A0A]/60">Chain hint:</span>
            <span className="font-semibold text-[#0A0A0A] capitalize">{chainHint}</span>
            <Link
              href="/markets"
              className="text-xs text-[#C8512C] underline hover:no-underline ml-1"
            >
              Clear
            </Link>
          </div>
        )}

        {/* Search + status */}
        <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('search')}
            className="px-4 py-3 border border-[#0A0A0A]/15 rounded-lg text-sm bg-white focus:border-[#C8512C] focus:outline-none transition-colors w-full max-w-[320px]"
          />
          <div className="text-xs text-[#0A0A0A]/50">
            {stale && <span className="text-[#C8512C]">Prices may be slightly delayed · </span>}
            {tokens && `${filtered.length} tokens`} · Live · updates every 30s
          </div>
        </div>

        {/* Table */}
        <div className="border border-[#0A0A0A]/10 rounded-2xl overflow-hidden bg-white">
          <table className="w-full">
            <thead className="bg-[#FAFAFA] border-b border-[#0A0A0A]/8">
              <tr>
                <SortHeader label="#" k="market_cap_rank" />
                <th className="text-xs tracking-[0.12em] text-[#0A0A0A]/60 font-medium py-4 px-4 uppercase text-left">
                  Token
                </th>
                <SortHeader label="Price" k="current_price" align="right" />
                <SortHeader label="24h" k="price_change_percentage_24h" align="right" />
                <SortHeader label="7d" k="price_change_percentage_7d_in_currency" align="right" />
                <SortHeader label="Volume" k="total_volume" align="right" />
                <SortHeader label="Market cap" k="market_cap" align="right" />
                <th className="text-xs tracking-[0.12em] text-[#0A0A0A]/60 font-medium py-4 px-4 uppercase text-right">
                  Last 7d
                </th>
              </tr>
            </thead>
            <tbody>
              {loading && !tokens && (
                <tr>
                  <td colSpan={8} className="text-center py-20 text-[#0A0A0A]/50">
                    Loading markets…
                  </td>
                </tr>
              )}
              {!loading && !tokens && error && (
                <tr>
                  <td colSpan={8} className="text-center py-20">
                    <div className="text-[#D4342E] font-medium mb-2">Failed to load markets</div>
                    <div className="text-sm text-[#0A0A0A]/60 mb-4">
                      {error.message?.includes('429')
                        ? 'Rate limit reached. Try again in a few seconds.'
                        : 'Could not reach CoinGecko. Check your network and retry.'}
                    </div>
                    <button
                      onClick={() => window.location.reload()}
                      className="text-sm font-medium text-[#C8512C] hover:underline"
                    >
                      Reload
                    </button>
                  </td>
                </tr>
              )}
              {!loading && tokens && filtered.length === 0 && query && (
                <tr>
                  <td colSpan={8} className="text-center py-20 text-[#0A0A0A]/50">
                    No tokens found for &quot;{query}&quot;.
                  </td>
                </tr>
              )}
              {!loading && tokens && filtered.length === 0 && !query && (
                <tr>
                  <td colSpan={8} className="text-center py-20 text-[#0A0A0A]/50">
                    No markets data available right now.
                  </td>
                </tr>
              )}
              {filtered.map((token) => {
                const pos24 = token.price_change_percentage_24h >= 0;
                const pos7d = (token.price_change_percentage_7d_in_currency ?? 0) >= 0;
                return (
                  <tr
                    key={token.id}
                    className="border-b border-[#0A0A0A]/5 last:border-0 hover:bg-[#FAFAFA] transition-colors"
                  >
                    <td className="py-4 px-4 text-sm text-[#0A0A0A]/60">
                      {token.market_cap_rank}
                    </td>
                    <td className="py-4 px-4">
                      <Link
                        href={`/token/${token.id}`}
                        className="flex items-center gap-3 hover:text-[#C8512C] transition-colors"
                      >
                        <img
                          src={token.image}
                          alt={token.name}
                          className="w-8 h-8 rounded-full"
                        />
                        <div>
                          <div className="text-sm font-medium text-[#0A0A0A]">
                            {token.name}
                          </div>
                          <div className="text-[11px] text-[#0A0A0A]/50 uppercase">
                            {token.symbol}
                          </div>
                        </div>
                      </Link>
                    </td>
                    <td className="py-4 px-4 text-sm font-medium text-[#0A0A0A] text-right">
                      <AnimatedNumber
                        value={token.current_price}
                        format={formatPrice}
                      />
                    </td>
                    <td className="py-4 px-4 text-right">
                      <span
                        className={`text-sm font-medium ${
                          pos24 ? 'text-[#0E9F6E]' : 'text-[#D4342E]'
                        }`}
                      >
                        {pos24 ? '▲' : '▼'}{' '}
                        {Math.abs(token.price_change_percentage_24h).toFixed(2)}%
                      </span>
                    </td>
                    <td className="py-4 px-4 text-right">
                      {token.price_change_percentage_7d_in_currency !== undefined && (
                        <span
                          className={`text-sm font-medium ${
                            pos7d ? 'text-[#0E9F6E]' : 'text-[#D4342E]'
                          }`}
                        >
                          {pos7d ? '▲' : '▼'}{' '}
                          {Math.abs(token.price_change_percentage_7d_in_currency).toFixed(2)}%
                        </span>
                      )}
                    </td>
                    <td className="py-4 px-4 text-sm text-[#0A0A0A]/70 text-right">
                      {formatCompact(token.total_volume)}
                    </td>
                    <td className="py-4 px-4 text-sm text-[#0A0A0A]/70 text-right">
                      {formatCompact(token.market_cap)}
                    </td>
                    <td className="py-4 px-4 flex justify-end">
                      <Sparkline
                        data={token.sparkline_in_7d?.price ?? []}
                        positive={pos7d}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between mt-8">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-5 py-3 border border-[#0A0A0A]/15 rounded-lg text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#0A0A0A]/5 transition-colors"
          >
            ← Previous
          </button>
          <span className="text-sm text-[#0A0A0A]/60">
            Page {page}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={!tokens || tokens.length < perPage}
            className="px-5 py-3 border border-[#0A0A0A]/15 rounded-lg text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#0A0A0A]/5 transition-colors"
          >
            Next →
          </button>
        </div>

        {/* Back to home */}
        <div className="mt-16 text-center">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-sm font-medium text-[#0A0A0A]/60 hover:text-[#C8512C] transition-colors"
          >
            ← Back to home
          </Link>
        </div>

      </div>
    </main>
  );
}
