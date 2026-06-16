
import jsPDF from 'jspdf'
import QRCode from 'qrcode'

export interface PdfReceiptParams {
  txHash:      string
  timestamp:   string
  sender:      string
  recipient:   string
  grossAmount: string
  netAmount:   string
  feeAmount:   string
  symbol:      string
  paymentRef:  string
  fiscalRef:   string
  eurValue?:   string
  network:     string

  // ── Identità legale emittente ──
  emittente?: {
    legalName: string
    vatNumber: string
    registeredOffice: string
    pec?: string
    rea?: string
  }

  // ── Identità controparte (se nota) ──
  controparte?: {
    name?: string
    vatNumber?: string
    fiscalCode?: string
    address?: string
  }

  // ── Tasso di cambio verificabile ──
  exchangeRate?: {
    tokenSymbol: string
    fiatCurrency: string
    rate: number
    source: string
    fetchedAt: string
  }

  // ── Explorer URL override per chain diverse da Base ──
  explorerUrl?: string
}

export async function generatePdfReceipt(p: PdfReceiptParams): Promise<void> {
  const doc  = new jsPDF({ unit: 'mm', format: 'a4' })
  const isEurc = p.symbol.toUpperCase() === 'EURC'

  // Modalità del template: crypto (controvalore EUR) vs eur_stable (importo già in EUR).
  // Determinata come oggi dal symbol EURC — l'asset è denominato in euro, nessuna conversione FX.
  const mode: 'crypto' | 'eur_stable' = isEurc ? 'eur_stable' : 'crypto'

  // Explorer URL — supporta tutte le chain
  const explorerUrl = p.explorerUrl || (
    p.network.includes('Sepolia') ? `https://sepolia.basescan.org/tx/${p.txHash}` :
    p.network.includes('Ethereum') ? `https://etherscan.io/tx/${p.txHash}` :
    p.network.includes('Arbitrum') ? `https://arbiscan.io/tx/${p.txHash}` :
    p.network.includes('Optimism') ? `https://optimistic.etherscan.io/tx/${p.txHash}` :
    p.network.includes('Polygon') ? `https://polygonscan.com/tx/${p.txHash}` :
    p.network.includes('BNB') ? `https://bscscan.com/tx/${p.txHash}` :
    p.network.includes('Avalanche') ? `https://snowtrace.io/tx/${p.txHash}` :
    p.network.includes('Solana') ? `https://solscan.io/tx/${p.txHash}` :
    p.network.includes('Tron') || p.network.includes('TRON') ? `https://tronscan.org/#/transaction/${p.txHash}` :
    `https://basescan.org/tx/${p.txHash}`
  )

  // ── Generate QR code as base64 PNG ────────────────────────────────────
  // Fondo chiaro → QR scuro su bianco (prima era chiaro su trasparente = invisibile)
  const qrDataUrl = await QRCode.toDataURL(explorerUrl, {
    width: 400,
    margin: 0,
    color: { dark: '#0A0A0A', light: '#FFFFFF' },
    errorCorrectionLevel: 'M',
  })

  // ── Palette brand chiara ───────────────────────────────────────────────
  // Documento fiscale → fondo chiaro, accento terracotta, success solo per "CONFERMATA".
  const C = {
    paper:      [250, 250, 250] as [number,number,number], // #FAFAFA fondo pagina
    ink:        [10,  10,  10 ] as [number,number,number], // #0A0A0A testo primario
    ink55:      [120, 120, 120] as [number,number,number], // label / secondario
    ink40:      [160, 160, 160] as [number,number,number], // disclaimer piccolo
    ink12:      [225, 225, 225] as [number,number,number], // bordi / divisori
    terracotta: [200, 81,  44 ] as [number,number,number], // #C8512C accento brand
    wash:       [245, 232, 224] as [number,number,number], // #F5E8E0 fondino tenue
    success:    [22,  163, 74 ] as [number,number,number], // #16A34A badge CONFERMATA
    successBg:  [223, 242, 230] as [number,number,number], // pill tenue del badge
    white:      [255, 255, 255] as [number,number,number],
  }

  const W = 210, H = 297
  const ml = 18, mr = 18
  const contentW = W - ml - mr

  // ── Helper: scarta valori vuoti o placeholder (es. "IT______", "(da configurare)") ──
  const real = (v?: string): string => {
    const s = (v || '').trim()
    if (!s) return ''
    if (s.includes('___') || /configurare/i.test(s)) return ''
    return s
  }

  // Dati emittente — opzionali: l'entità reale sarà RPagos S.R.L. (Costa Rica), non una S.r.l.
  // italiana. Se un campo manca/è placeholder → si omette la riga, niente placeholder italiani.
  // TODO(legal): sostituire con dati reali RPagos S.R.L.
  const emiName = real(p.emittente?.legalName) || '[EMITTENTE — DATI DA CONFIGURARE]'
  const emiVat  = real(p.emittente?.vatNumber)
  const emiPec  = real(p.emittente?.pec)
  const emiRea  = real(p.emittente?.rea)
  const emiOffice = real(p.emittente?.registeredOffice)
  const emiDetailParts = [
    emiOffice,
    emiVat ? `P.IVA ${emiVat}` : '',
    emiPec ? `PEC ${emiPec}` : '',
    emiRea ? `REA ${emiRea}` : '',
  ].filter(Boolean)

  // ── Background pagina ──────────────────────────────────────────────────
  doc.setFillColor(...C.paper)
  doc.rect(0, 0, W, H, 'F')

  // Sottile accento terracotta in testa
  doc.setFillColor(...C.terracotta)
  doc.rect(0, 0, W, 1.2, 'F')

  // ── Header ─────────────────────────────────────────────────────────────
  // Wordmark in ink (non verde)
  doc.setTextColor(...C.ink)
  doc.setFontSize(24)
  doc.setFont('helvetica', 'bold')
  doc.text('RSends', ml, 18)

  doc.setTextColor(...C.ink55)
  doc.setFontSize(7)
  doc.setFont('helvetica', 'normal')
  doc.text('Gateway di Pagamento B2B Multi-chain', ml, 23)

  // Riga emittente (campi presenti)
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6.5)
  doc.setFont('helvetica', 'bold')
  doc.text(emiName, ml, 29)
  if (emiDetailParts.length) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6)
    doc.text(emiDetailParts.join('  ·  '), ml, 33)
  }

  // Badge CONFERMATA (uno solo) — pill success tenue, testo success
  const badgeW = 34, badgeH = 9, badgeX = W - mr - badgeW, badgeY = 13
  doc.setFillColor(...C.successBg)
  doc.roundedRect(badgeX, badgeY, badgeW, badgeH, 2, 2, 'F')
  doc.setTextColor(...C.success)
  doc.setFontSize(7.5)
  doc.setFont('helvetica', 'bold')
  doc.text('CONFERMATA', badgeX + badgeW / 2, badgeY + 5.8, { align: 'center' })

  // ── Titolo documento (sempre lo stesso, coerente col disclaimer DPR 633/72) ──
  doc.setTextColor(...C.terracotta)
  doc.setFontSize(15)
  doc.setFont('helvetica', 'bold')
  doc.text('Ricevuta di Pagamento On-Chain', ml, 44)

  // Sottotitolo: specificità EUR/stablecoin come testo, non come secondo badge
  doc.setTextColor(...C.ink55)
  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  const subtitle = mode === 'eur_stable'
    ? `Euro Stablecoin — ${p.symbol} su ${p.network}`
    : `Transazione on-chain · ${p.network}`
  doc.text(subtitle, ml, 49)

  // Divisore
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.line(ml, 53, W - mr, 53)

  let y = 58

  // ── Riga meta ──────────────────────────────────────────────────────────
  const metaH = 15
  doc.setFillColor(...C.white)
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.roundedRect(ml, y, contentW, metaH, 2, 2, 'FD')

  const metaCols = [
    { label: 'DATA', value: new Date(p.timestamp).toLocaleString('it-IT') },
    { label: 'NETWORK', value: p.network },
    { label: 'TX HASH', value: p.txHash.slice(0, 14) + '…' + p.txHash.slice(-6) },
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
  y += metaH + 6

  // ── Card IMPORTO LORDO ─────────────────────────────────────────────────
  const cardH = 36
  doc.setFillColor(...C.wash)
  doc.roundedRect(ml, y, contentW, cardH, 3, 3, 'F')
  doc.setDrawColor(...C.terracotta)
  doc.setLineWidth(0.4)
  doc.roundedRect(ml, y, contentW, cardH, 3, 3, 'S')

  const amtLabel = mode === 'eur_stable' ? 'IMPORTO LORDO (EUR)' : `IMPORTO LORDO (${p.symbol})`
  doc.setTextColor(...C.ink55)
  doc.setFontSize(7)
  doc.setFont('helvetica', 'bold')
  doc.text(amtLabel, ml + 8, y + 9)

  const grossDisplay = mode === 'eur_stable'
    ? `€ ${p.grossAmount}`
    : `${p.grossAmount} ${p.symbol}`
  doc.setTextColor(...C.ink)
  doc.setFontSize(26)
  doc.setFont('helvetica', 'bold')
  doc.text(grossDisplay, ml + 8, y + 24)

  if (mode === 'crypto') {
    // Controvalore EUR con fonte verificabile a lato destro
    if (p.exchangeRate && p.exchangeRate.rate > 0) {
      const grossNum = parseFloat(p.grossAmount) || 0
      const eurCalc = (grossNum * p.exchangeRate.rate).toFixed(2)

      doc.setFontSize(11)
      doc.setTextColor(...C.ink55)
      doc.setFont('helvetica', 'bold')
      doc.text(`€ ${eurCalc}`, W - mr - 8, y + 12, { align: 'right' })

      doc.setFontSize(5.5)
      doc.setTextColor(...C.ink55)
      doc.setFont('helvetica', 'normal')
      doc.text(
        `1 ${p.exchangeRate.tokenSymbol} = € ${p.exchangeRate.rate.toFixed(2)}`,
        W - mr - 8, y + 18, { align: 'right' }
      )
      doc.text(`Fonte: ${p.exchangeRate.source}`, W - mr - 8, y + 22, { align: 'right' })
      doc.text(
        `Rilevato: ${new Date(p.exchangeRate.fetchedAt).toLocaleString('it-IT')}`,
        W - mr - 8, y + 26, { align: 'right' }
      )
    } else if (p.eurValue) {
      doc.setFontSize(11)
      doc.setTextColor(...C.ink55)
      doc.setFont('helvetica', 'normal')
      doc.text(`≈ € ${p.eurValue}`, W - mr - 8, y + 12, { align: 'right' })
      doc.setFontSize(5.5)
      doc.setTextColor(...C.ink40)
      doc.text('(stima — tasso non verificato)', W - mr - 8, y + 17, { align: 'right' })
    }
  } else {
    // eur_stable: nessuna conversione FX
    doc.setFontSize(6.5)
    doc.setTextColor(...C.ink55)
    doc.setFont('helvetica', 'normal')
    doc.text(
      `Valuta: EUR · Token su ${p.network} · Nessuna conversione FX`,
      ml + 8, y + 32
    )
  }

  y += cardH + 7

  // ── Tabella breakdown ──────────────────────────────────────────────────
  const rows = [
    {
      label: 'Importo Netto (99.5%)',
      value: mode === 'eur_stable' ? `€ ${p.netAmount}` : `${p.netAmount} ${p.symbol}`,
    },
    {
      label: 'Commissione Gateway (0.5%)',
      value: mode === 'eur_stable' ? `€ ${p.feeAmount}` : `${p.feeAmount} ${p.symbol}`,
    },
    {
      label: 'Tipo Transazione',
      value: mode === 'eur_stable' ? 'Euro Stablecoin (ERC-20)' : `Cripto Asset (${p.symbol})`,
    },
  ]

  const rowH = 8
  rows.forEach((row, i) => {
    const rowY = y + i * rowH
    doc.setTextColor(...C.ink55)
    doc.setFontSize(7.5)
    doc.setFont('helvetica', 'normal')
    doc.text(row.label, ml + 2, rowY + 5.5)

    doc.setTextColor(...C.ink)
    doc.setFont('courier', 'normal')
    doc.setFontSize(7.5)
    doc.text(row.value, W - mr - 2, rowY + 5.5, { align: 'right' })

    // Divisore inferiore tenue
    doc.setDrawColor(...C.ink12)
    doc.setLineWidth(0.2)
    doc.line(ml, rowY + rowH, W - mr, rowY + rowH)
  })

  y += rows.length * rowH + 6

  // ── Parti dell'operazione ──────────────────────────────────────────────
  // Mittente (ordinante)
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6.5)
  doc.setFont('helvetica', 'bold')
  doc.text('MITTENTE (ORDINANTE)', ml, y)
  doc.setTextColor(...C.ink)
  doc.setFontSize(7.5)
  doc.setFont('courier', 'normal')
  doc.text(p.sender, ml, y + 5)
  if (p.controparte?.name) {
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(...C.ink55)
    doc.setFontSize(6)
    doc.text(
      p.controparte.name + (p.controparte.vatNumber ? `  ·  P.IVA: ${p.controparte.vatNumber}` : ''),
      ml, y + 9
    )
  } else {
    doc.setFont('helvetica', 'italic')
    doc.setTextColor(...C.ink40)
    doc.setFontSize(5.5)
    doc.text('Identità non verificata — solo indirizzo blockchain', ml, y + 9)
  }
  y += 13

  // Destinatario (beneficiario)
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6.5)
  doc.setFont('helvetica', 'bold')
  doc.text('DESTINATARIO (BENEFICIARIO)', ml, y)
  doc.setTextColor(...C.ink)
  doc.setFontSize(7.5)
  doc.setFont('courier', 'normal')
  doc.text(p.recipient, ml, y + 5)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...C.ink55)
  doc.setFontSize(6)
  doc.text(emiName + (emiVat ? `  ·  P.IVA: ${emiVat}` : ''), ml, y + 9)
  y += 14

  // ── Dati fiscali (DAC8/MiCA) ───────────────────────────────────────────
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.line(ml, y, W - mr, y)
  y += 4

  const fiscalH = 21
  doc.setFillColor(...C.wash)
  doc.roundedRect(ml, y, contentW, fiscalH, 2, 2, 'F')

  doc.setTextColor(...C.terracotta)
  doc.setFontSize(6.5)
  doc.setFont('helvetica', 'bold')
  doc.text('DATI FISCALI (DAC8/MiCA)', ml + 6, y + 6)

  const fiscalRows = [
    { key: 'payment_ref', val: p.paymentRef },
    { key: 'fiscal_ref',  val: p.fiscalRef },
  ]
  fiscalRows.forEach(({ key, val }, i) => {
    const fy = y + 12 + i * 6
    doc.setTextColor(...C.ink55)
    doc.setFontSize(6)
    doc.setFont('courier', 'normal')
    doc.text(key, ml + 6, fy)
    doc.setTextColor(...C.ink)
    doc.text(val.slice(0, 64), ml + 32, fy)
  })

  y += fiscalH + 4

  // ── Blocco conformità UE — SOLO eur_stable, sobrio e non decorativo ─────
  if (mode === 'eur_stable') {
    const compH = 14
    doc.setFillColor(...C.wash)
    doc.roundedRect(ml, y, contentW, compH, 2, 2, 'F')
    doc.setDrawColor(...C.ink12)
    doc.setLineWidth(0.3)
    doc.roundedRect(ml, y, contentW, compH, 2, 2, 'S')

    doc.setTextColor(...C.ink55)
    doc.setFontSize(6)
    doc.setFont('helvetica', 'bold')
    doc.text('CONFORMITÀ', ml + 6, y + 5)

    doc.setTextColor(...C.ink55)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(5.5)
    // TODO(legal): verificare citazioni normative applicabili.
    doc.text('Documento conforme a fini di rendicontazione.', ml + 6, y + 9)
    doc.text(
      `Token ${p.symbol} (Circle) · Valuta EUR · Nessuna conversione FX`,
      ml + 6, y + 12.5
    )
    y += compH + 4
  }

  // ── Verifica On-Chain ──────────────────────────────────────────────────
  const verH = 28
  doc.setFillColor(...C.white)
  doc.roundedRect(ml, y, contentW, verH, 2, 2, 'F')
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.roundedRect(ml, y, contentW, verH, 2, 2, 'S')

  const qrSize = 20
  doc.addImage(qrDataUrl, 'PNG', ml + 4, y + 4, qrSize, qrSize)

  const txLeft = ml + 4 + qrSize + 6
  doc.setTextColor(...C.terracotta)
  doc.setFontSize(7)
  doc.setFont('helvetica', 'bold')
  doc.text('Verifica On-Chain', txLeft, y + 7)

  doc.setTextColor(...C.ink55)
  doc.setFontSize(5.5)
  doc.setFont('helvetica', 'normal')
  doc.text('Scansiona il QR o visita il link per verificare la transazione:', txLeft, y + 12)

  doc.setTextColor(...C.terracotta)
  doc.setFontSize(5)
  doc.setFont('courier', 'normal')
  if (explorerUrl.length > 70) {
    doc.text(explorerUrl.slice(0, 70), txLeft, y + 17)
    doc.text(explorerUrl.slice(70), txLeft, y + 21)
  } else {
    doc.text(explorerUrl, txLeft, y + 17)
  }

  doc.setTextColor(...C.ink40)
  doc.setFontSize(4.5)
  doc.text('Transazione immutabile e verificabile pubblicamente sulla blockchain.', txLeft, y + 25)

  y += verH + 4

  // ── Hash di integrità documento ────────────────────────────────────────
  const canonical = [
    p.txHash, p.timestamp, p.sender, p.recipient,
    p.grossAmount, p.netAmount, p.feeAmount, p.symbol,
    p.paymentRef, p.fiscalRef, p.network,
    p.exchangeRate ? `${p.exchangeRate.rate}:${p.exchangeRate.source}:${p.exchangeRate.fetchedAt}` : '',
  ].join('|')

  const encoded = new TextEncoder().encode(canonical)
  const hashBuffer = await crypto.subtle.digest('SHA-256', encoded.buffer as ArrayBuffer)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  const documentHash = hashArray.map(b => b.toString(16).padStart(2, '0')).join('')

  doc.setFillColor(...C.white)
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.2)
  doc.roundedRect(ml, y, contentW, 10, 2, 2, 'FD')
  doc.setTextColor(...C.ink55)
  doc.setFontSize(5)
  doc.setFont('helvetica', 'bold')
  doc.text('HASH INTEGRITÀ DOCUMENTO (SHA-256)', ml + 4, y + 4)
  doc.setFont('courier', 'normal')
  doc.setFontSize(4)
  doc.setTextColor(...C.ink55)
  doc.text(documentHash, ml + 4, y + 8)

  // ── Footer con disclaimer legale ───────────────────────────────────────
  const footerH = 20
  doc.setDrawColor(...C.ink12)
  doc.setLineWidth(0.3)
  doc.line(0, H - footerH, W, H - footerH)

  doc.setTextColor(...C.ink55)
  doc.setFontSize(5)
  doc.setFont('helvetica', 'normal')
  doc.text(
    `${emiName}${emiVat ? '  ·  P.IVA ' + emiVat : ''}  ·  rsend.io`,
    ml, H - footerH + 6
  )

  doc.setTextColor(...C.ink40)
  doc.setFontSize(4.5)
  doc.text(
    'Documento attestante operazione su blockchain. Non costituisce fattura ai sensi del DPR 633/72.',
    ml, H - footerH + 11
  )
  doc.text(
    'I valori in EUR sono indicativi e basati sul tasso riportato. Per fatturazione elettronica (SDI): compliance@rsend.io',
    ml, H - footerH + 15
  )

  doc.setTextColor(...C.ink40)
  doc.setFontSize(4.5)
  doc.text(
    `Generato: ${new Date().toLocaleString('it-IT')}  ·  Hash: ${documentHash.slice(0, 16)}...`,
    W - mr, H - footerH + 6, { align: 'right' }
  )

  // ── Save ───────────────────────────────────────────────────────────────
  const slug = p.txHash.slice(2, 10)
  const filename = isEurc
    ? `RSends_EURC_${slug}.pdf`
    : `RSends_${p.symbol}_${slug}.pdf`

  doc.save(filename)
}
