/**
 * Test script — genera la fattura PDF di prova (Step 3) con dati fittizi.
 * Scenario spec: periodo mensile, ~184.000 tx × €0,01 = €1.840,00.
 * IVA/regime PARAMETRICI-vuoti (tax_* null → "—" nel PDF, nessun valore inventato).
 * Esegui: npx tsx scripts/test-invoice.ts
 */
import { buildInvoiceDoc } from '../lib/usePdfInvoice'
import { writeFileSync } from 'fs'
import { join } from 'path'

const doc = buildInvoiceDoc({
  invoice_number: 'FAT-2026-000001',
  status: 'issued',
  created_at: '2026-06-01T09:00:00Z',
  issued_at: '2026-06-01T09:05:00Z',
  period_start: '2026-05-01T00:00:00Z',
  // 21:59:59Z = 23:59:59 CEST → la data resta 31/05 anche in rendering locale IT.
  period_end: '2026-05-31T21:59:59Z',
  tx_count: 184000,
  unit_price_eur: '0.01',
  subtotal_eur: '1840.00',
  tax_regime: null,
  tax_rate: null,
  tax_amount_eur: null,
  tax_note: null,
  total_eur: '1840.00',

  // Emittente: placeholder reale del service (ISSUER_SNAPSHOT) —
  // TODO(legal): RPagos S.R.L. (Costa Rica), dati da configurare.
  snapshot_issuer: {
    legal_name: '[EMITTENTE — DATI DA CONFIGURARE]',
    vat_number: null,
    address: null,
    country: null,
    email: null,
  },

  // Cliente fittizio con anagrafica COMPLETA (così la fattura è emissibile).
  snapshot_client: {
    owner_address: '0x742d35cc6634c0532925a3b844bc9e7595f2bd18',
    billing_legal_name: 'ACME Commercio S.r.l.',
    billing_vat_number: 'IT01234567890',
    billing_tax_code: '01234567890',
    billing_address_line: 'Via Esempio 42',
    billing_city: 'Milano',
    billing_postal_code: '20121',
    billing_country: 'IT',
    billing_email: 'amministrazione@acme-commercio.it',
    billing_pec: 'acme@pec.it',
  },
})

const outPath = join(process.cwd(), 'RSends_FAT-2026-000001_SAMPLE.pdf')
writeFileSync(outPath, Buffer.from(doc.output('arraybuffer')))
console.log(`✅ Fattura di prova salvata: ${outPath}`)
