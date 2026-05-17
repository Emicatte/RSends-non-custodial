'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import { useCoinGecko } from '@/hooks/useCoinGecko';
import AnimatedNumber from '@/components/motion/AnimatedNumber';
import { Link } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';

const PriceChart = dynamic(() => import('./PriceChart'), { ssr: false });

type TokenDetail = {
  id: string;
  symbol: string;
  name: string;
  image: { large: string };
  market_cap_rank: number;
  market_data: {
    current_price: { usd: number };
    price_change_percentage_24h: number;
    market_cap: { usd: number };
    total_volume: { usd: number };
    circulating_supply: number;
    max_supply: number | null;
    ath: { usd: number };
    ath_date: { usd: string };
    atl: { usd: number };
    atl_date: { usd: string };
  };
  description: { en: string };
  links: {
    homepage: string[];
    blockchain_site: string[];
    twitter_screen_name: string;
  };
  categories: string[];
};

type ChartRange = '1' | '7' | '30' | '90' | '365';

const RANGES: Array<{ key: ChartRange; label: string }> = [
  { key: '1', label: '1D' },
  { key: '7', label: '7D' },
  { key: '30', label: '30D' },
  { key: '90', label: '90D' },
  { key: '365', label: '1Y' },
];

function formatCompact(n: number): string {
  if (!n) return '—';
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

function formatSupply(n: number | null): string {
  if (!n) return 'Unlimited';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function formatTokenPrice(n: number): string {
  const decimals = n < 1 ? 4 : 2;
  return '$' + n.toFixed(decimals);
}

// Strip HTML from CoinGecko description
function stripHtml(html: string): string {
  if (typeof window === 'undefined') return html.replace(/<[^>]*>/g, '');
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.textContent || div.innerText || '';
}

export default function TokenClient({ id }: { id: string }) {
  const t = useTranslations('markets');
  const [range, setRange] = useState<ChartRange>('7');

  const { data: token, stale, loading } = useCoinGecko<TokenDetail>(
    `https://api.coingecko.com/api/v3/coins/${id}?localization=false&tickers=false&community_data=false&developer_data=false`,
    `token_${id}`,
    { ttlMs: 5 * 60_000, refreshIntervalMs: 60_000 }
  );

  const { data: history, loading: historyLoading } = useCoinGecko<{ prices: [number, number][] }>(
    `https://api.coingecko.com/api/v3/coins/${id}/market_chart?vs_currency=usd&days=${range}`,
    `history_${id}_${range}`,
    { ttlMs: 10 * 60_000 }
  );

  if (loading && !token) {
    return (
      <main className="min-h-screen py-32">
        <div className="mx-auto max-w-[1440px] px-4 md:px-24">
          <div className="text-[#0A0A0A]/50">Loading {id}…</div>
        </div>
      </main>
    );
  }

  if (!token) {
    return (
      <main className="min-h-screen py-32">
        <div className="mx-auto max-w-[1440px] px-4 md:px-24">
          <h1 className="text-[48px] font-semibold text-[#0A0A0A] mb-4">
            Token not found
          </h1>
          <p className="text-[#0A0A0A]/70 mb-8">
            We couldn&apos;t load data for &quot;{id}&quot;. It might not exist or the rate limit was hit.
          </p>
          <Link
            href="/markets"
            className="inline-flex items-center gap-2 bg-[#0A0A0A] text-white px-6 py-3 rounded-lg"
          >
            ← Markets
          </Link>
        </div>
      </main>
    );
  }

  const md = token.market_data;
  const pos24 = md.price_change_percentage_24h >= 0;

  return (
    <main className="min-h-screen py-20">
      <div className="mx-auto max-w-[1440px] px-24">

        {/* Breadcrumb */}
        <nav className="mb-10 text-sm" aria-label="Breadcrumb">
          <ol className="flex items-center gap-2 text-[#0A0A0A]/60">
            <li>
              <Link href="/" className="hover:text-[#C8512C] transition-colors">
                Home
              </Link>
            </li>
            <li className="text-[#0A0A0A]/30">/</li>
            <li>
              <Link href="/markets" className="hover:text-[#C8512C] transition-colors">
                Markets
              </Link>
            </li>
            <li className="text-[#0A0A0A]/30">/</li>
            <li className="text-[#0A0A0A] font-medium">{token.name}</li>
          </ol>
        </nav>

        {/* Header: token info */}
        <div className="flex items-start gap-8 mb-12 flex-wrap">
          <img
            src={token.image.large}
            alt={token.name}
            className="w-20 h-20 rounded-full"
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-4 mb-3 flex-wrap">
              <h1 className="text-[56px] leading-[1] tracking-[-0.02em] font-semibold text-[#0A0A0A]">
                {token.name}
              </h1>
              <span className="text-2xl text-[#0A0A0A]/50 uppercase font-medium">
                {token.symbol}
              </span>
              {token.market_cap_rank && (
                <span className="text-xs px-3 py-1 bg-[#0A0A0A]/5 rounded-full text-[#0A0A0A]/70 font-medium">
                  Rank #{token.market_cap_rank}
                </span>
              )}
            </div>
            <div className="flex items-baseline gap-4 flex-wrap">
              <div className="text-[48px] font-semibold text-[#0A0A0A] leading-none">
                <AnimatedNumber
                  value={md.current_price.usd}
                  format={formatTokenPrice}
                />
              </div>
              <span
                className={`text-xl font-medium ${
                  pos24 ? 'text-[#0E9F6E]' : 'text-[#D4342E]'
                }`}
              >
                {pos24 ? '▲' : '▼'} {Math.abs(md.price_change_percentage_24h).toFixed(2)}%
              </span>
              <span className="text-sm text-[#0A0A0A]/50">(24h)</span>
            </div>
            {stale && (
              <p className="text-xs text-[#C8512C] mt-3">
                Prices may be slightly delayed due to rate limiting.
              </p>
            )}
          </div>

          <Link
            href={`/app?token=${token.id}`}
            className="bg-[#0A0A0A] text-white px-6 py-3 rounded-lg font-medium hover:bg-[#0A0A0A]/90 transition-colors"
          >
            Open in RSends →
          </Link>
        </div>

        {/* Chart + range selector */}
        <div className="border border-[#0A0A0A]/10 rounded-2xl bg-white p-6 mb-12">
          <div className="flex items-center justify-between mb-6 flex-wrap gap-4">
            <h2 className="text-xl font-semibold text-[#0A0A0A]">Price chart</h2>
            <div className="flex gap-1 bg-[#FAFAFA] p-1 rounded-lg">
              {RANGES.map((r) => (
                <button
                  key={r.key}
                  onClick={() => setRange(r.key)}
                  disabled={historyLoading}
                  className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                    range === r.key
                      ? 'bg-white text-[#0A0A0A] shadow-sm'
                      : 'text-[#0A0A0A]/60 hover:text-[#0A0A0A]'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <div className="relative" style={{ width: '100%', height: 400 }}>
            <PriceChart history={history} range={range} />
            {!history?.prices?.length && (
              <div className="absolute inset-0 flex items-center justify-center text-[#0A0A0A]/40 bg-white">
                Loading chart…
              </div>
            )}
          </div>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-12">
          {[
            { label: 'Market cap', value: formatCompact(md.market_cap.usd) },
            { label: '24h volume', value: formatCompact(md.total_volume.usd) },
            { label: 'Circulating supply', value: formatSupply(md.circulating_supply) },
            { label: 'Max supply', value: formatSupply(md.max_supply) },
            { label: 'All-time high', value: formatCompact(md.ath.usd), sub: formatDate(md.ath_date.usd) },
            { label: 'All-time low', value: formatCompact(md.atl.usd), sub: formatDate(md.atl_date.usd) },
          ].map((s) => (
            <div
              key={s.label}
              className="bg-[#FAFAFA] border border-[#0A0A0A]/5 rounded-xl p-5"
            >
              <div className="text-xs tracking-[0.12em] text-[#0A0A0A]/60 uppercase font-medium mb-2">
                {s.label}
              </div>
              <div className="text-xl font-semibold text-[#0A0A0A]">
                {s.value}
              </div>
              {'sub' in s && s.sub && (
                <div className="text-xs text-[#0A0A0A]/50 mt-1">{s.sub}</div>
              )}
            </div>
          ))}
        </div>

        {/* Links + Description */}
        <div className="grid lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2">
            <h2 className="text-2xl font-semibold text-[#0A0A0A] mb-4">
              About {token.name}
            </h2>
            {token.description.en ? (
              <p className="text-[#0A0A0A]/80 leading-[1.7] whitespace-pre-line">
                {stripHtml(token.description.en).slice(0, 800)}
                {stripHtml(token.description.en).length > 800 && '…'}
              </p>
            ) : (
              <p className="text-[#0A0A0A]/50">No description available.</p>
            )}
          </div>

          <div>
            <h2 className="text-2xl font-semibold text-[#0A0A0A] mb-4">Links</h2>
            <div className="space-y-2">
              {token.links.homepage.filter(Boolean).slice(0, 1).map((url) => (
                <a
                  key={url}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between px-4 py-3 border border-[#0A0A0A]/10 rounded-lg hover:border-[#C8512C] transition-colors group"
                >
                  <span className="text-sm font-medium text-[#0A0A0A]">Website</span>
                  <span className="text-xs text-[#0A0A0A]/50 group-hover:text-[#C8512C] truncate max-w-[180px]">
                    {new URL(url).hostname} ↗
                  </span>
                </a>
              ))}
              {token.links.blockchain_site.filter(Boolean).slice(0, 1).map((url) => (
                <a
                  key={url}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between px-4 py-3 border border-[#0A0A0A]/10 rounded-lg hover:border-[#C8512C] transition-colors group"
                >
                  <span className="text-sm font-medium text-[#0A0A0A]">Explorer</span>
                  <span className="text-xs text-[#0A0A0A]/50 group-hover:text-[#C8512C] truncate max-w-[180px]">
                    {new URL(url).hostname} ↗
                  </span>
                </a>
              ))}
              {token.links.twitter_screen_name && (
                <a
                  href={`https://twitter.com/${token.links.twitter_screen_name}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between px-4 py-3 border border-[#0A0A0A]/10 rounded-lg hover:border-[#C8512C] transition-colors group"
                >
                  <span className="text-sm font-medium text-[#0A0A0A]">Twitter</span>
                  <span className="text-xs text-[#0A0A0A]/50 group-hover:text-[#C8512C]">
                    @{token.links.twitter_screen_name} ↗
                  </span>
                </a>
              )}
            </div>

            {token.categories && token.categories.length > 0 && (
              <div className="mt-8">
                <h3 className="text-sm tracking-[0.12em] uppercase text-[#0A0A0A]/60 font-medium mb-3">
                  Categories
                </h3>
                <div className="flex flex-wrap gap-2">
                  {token.categories.slice(0, 6).map((c) => (
                    <span
                      key={c}
                      className="text-xs px-3 py-1 bg-[#0A0A0A]/5 rounded-full text-[#0A0A0A]/70"
                    >
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
