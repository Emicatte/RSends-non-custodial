import type { Metadata } from 'next';
import MarketsClient from './MarketsClient';

export const metadata: Metadata = {
  title: 'Markets — RSends',
  description:
    'Track every crypto token across 11+ chains. Live prices, 24h changes, volume, and 7d sparklines — updated every 30 seconds.',
};

export default function MarketsPage() {
  return <MarketsClient />;
}
