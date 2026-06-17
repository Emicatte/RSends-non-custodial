import type { Metadata } from 'next';
import TokenClient from './TokenClient';

type Props = { params: Promise<{ id: string; locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const name = id.charAt(0).toUpperCase() + id.slice(1).replace(/-/g, ' ');
  return {
    title: `${name} price, chart & info — RSends`,
    description: `Live ${name} price, 7-day chart, market cap, volume, and more. Trade and swap ${name} on RSends.`,
  };
}

export default async function TokenPage({ params }: Props) {
  const { id } = await params;
  return <TokenClient id={id} />;
}
