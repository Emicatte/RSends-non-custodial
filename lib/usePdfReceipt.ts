
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
  const qrDataUrl = await QRCode.toDataURL(explorerUrl, {
    width: 400,
    margin: 0,
    color: { dark: '#e2e2f0', light: '#00000000' },
    errorCorrectionLevel: 'M',
  })

  // ── Palette ───────────────────────────────────────────────────────────
  const C = {
    bg:      [8,   8,   16]  as [number,number,number],
    card:    [17,  17,  32]  as [number,number,number],
    card2:   [22,  22,  40]  as [number,number,number],
    em:      [0,   255, 163] as [number,number,number],
    emSoft:  [0,   200, 130] as [number,number,number],
    text:    [226, 226, 240] as [number,number,number],
    muted:   [100, 100, 130] as [number,number,number],
    dim:     [60,  60,  85]  as [number,number,number],
    border:  [40,  40,  60]  as [number,number,number],
    euBlue:  [0,   51,  153] as [number,number,number],
    euGold:  [255, 204, 0]   as [number,number,number],
    white:   [255, 255, 255] as [number,number,number],
    success: [34,  197, 94]  as [number,number,number],
  }

  const W = 210, H = 297
  const ml = 18, mr = 18
  const contentW = W - ml - mr

  // ── Background ─────────────────────────────────────────────────────────
  doc.setFillColor(...C.bg)
  doc.rect(0, 0, W, H, 'F')

  // ── Top accent bar ─────────────────────────────────────────────────────
  doc.setFillColor(...C.em)
  doc.rect(0, 0, W, 2, 'F')

  // ── Header ─────────────────────────────────────────────────────────────
  doc.setFillColor(...C.card)
  doc.rect(0, 2, W, 48, 'F')

  // Brand
  doc.setTextColor(...C.em)
  doc.setFontSize(26)
  doc.setFont('helvetica', 'bold')
  doc.text('RSends', ml, 24)

  doc.setTextColor(...C.dim)
  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.text('Gateway di Pagamento B2B Multi-chain', ml, 31)

  // ── Identità legale emittente ──
  const emi = p.emittente || {
    legalName: 'RSend S.r.l.',
    vatNumber: 'IT______________',
    registeredOffice: '(sede legale da configurare)',
  }

  doc.setTextColor(...C.muted)
  doc.setFontSize(6)
  doc.setFont('helvetica', 'normal')
  doc.text(`${emi.legalName}  ·  P.IVA ${emi.vatNumber}`, ml, 36)
  doc.text(emi.registeredOffice + (emi.pec ? `  ·  PEC: ${emi.pec}` : ''), ml, 40)

  // Receipt title
  doc.setTextColor(...C.text)
  doc.setFontSize(13)
  doc.setFont('helvetica', 'bold')
  const title = isEurc
    ? 'Ricevuta Fiscale Europea — Euro Stablecoin'
    : 'Ricevuta di Pagamento On-Chain'
  doc.text(title, ml, 48)

  // EURC badge
  if (isEurc) {
    doc.setFillColor(...C.euBlue)
    doc.roundedRect(W - mr - 46, 14, 46, 12, 2, 2, 'F')
    doc.setTextColor(...C.euGold)
    doc.setFontSize(7)
    doc.setFont('helvetica', 'bold')
    doc.text('EURC · Euro Stablecoin', W - mr - 43, 22)
  }

  // Status badge
  doc.setFillColor(...C.success)
  doc.roundedRect(W - mr - 46, isEurc ? 34 : 18, 46, 12, 2, 2, 'F')
  doc.setTextColor(...C.bg)
  doc.setFontSize(7)
  doc.setFont('helvetica', 'bold')
  doc.text('CONFERMATA', W - mr - 23, isEurc ? 42 : 26, { align: 'center' })

  let y = 58

  // ── Metadata row ───────────────────────────────────────────────────────
  doc.setFillColor(...C.card2)
  doc.roundedRect(ml, y, contentW, 16, 3, 3, 'F')

  const metaCols = [
    { label: 'DATA', value: new Date(p.timestamp).toLocaleString('it-IT') },
    { label: 'NETWORK', value: p.network },
    { label: 'TX HASH', value: p.txHash.slice(0, 18) + '...' + p.txHash.slice(-6) },
  ]
  const colW = contentW / metaCols.length
  metaCols.forEach(({ label, value }, i) => {
    const x = ml + 6 + i * colW
    doc.setTextColor(...C.dim)
    doc.setFontSize(6)
    doc.setFont('helvetica', 'bold')
    doc.text(label, x, y + 6)
    doc.setTextColor(...C.text)
    doc.setFontSize(7)
    doc.setFont('courier', 'normal')
    doc.text(value, x, y + 12)
  })
  y += 22

  // ── Amount card ────────────────────────────────────────────────────────
  doc.setFillColor(...C.card)
  doc.roundedRect(ml, y, contentW, 38, 4, 4, 'F')
  doc.setDrawColor(...C.em)
  doc.setLineWidth(0.5)
  doc.roundedRect(ml, y, contentW, 38, 4, 4, 'S')

  // Label
  const amtLabel = isEurc ? 'IMPORTO LORDO (EUR)' : `IMPORTO LORDO (${p.symbol})`
  doc.setTextColor(...C.dim)
  doc.setFontSize(7)
  doc.setFont('helvetica', 'bold')
  doc.text(amtLabel, ml + 8, y + 10)

  // Amount
  const grossDisplay = isEurc
    ? `€ ${p.grossAmount}`
    : `${p.grossAmount} ${p.symbol}`
  doc.setTextColor(...C.em)
  doc.setFontSize(28)
  doc.setFont('helvetica', 'bold')
  doc.text(grossDisplay, ml + 8, y + 28)

  // EUR countervalue con fonte verificabile
  if (!isEurc) {
    if (p.exchangeRate && p.exchangeRate.rate > 0) {
      const grossNum = parseFloat(p.grossAmount) || 0
      const eurCalc = (grossNum * p.exchangeRate.rate).toFixed(2)

      doc.setFontSize(10)
      doc.setTextColor(...C.text)
      doc.setFont('helvetica', 'bold')
      doc.text(`€ ${eurCalc}`, W - mr - 8, y + 24, { align: 'right' })

      doc.setFontSize(5.5)
      doc.setTextColor(...C.dim)
      doc.setFont('helvetica', 'normal')
      doc.text(
        `1 ${p.exchangeRate.tokenSymbol} = € ${p.exchangeRate.rate.toFixed(2)}`,
        W - mr - 8, y + 29, { align: 'right' }
      )
      doc.text(
        `Fonte: ${p.exchangeRate.source}`,
        W - mr - 8, y + 33, { align: 'right' }
      )
      doc.text(
        `Rilevato: ${new Date(p.exchangeRate.fetchedAt).toLocaleString('it-IT')}`,
        W - mr - 8, y + 37, { align: 'right' }
      )
    } else if (p.eurValue) {
      doc.setFontSize(10)
      doc.setTextColor(...C.muted)
      doc.setFont('helvetica', 'normal')
      doc.text(`≈ € ${p.eurValue}`, W - mr - 8, y + 28, { align: 'right' })
      doc.setFontSize(5)
      doc.setTextColor(...C.dim)
      doc.text('(stima — tasso non verificato)', W - mr - 8, y + 33, { align: 'right' })
    }
  }

  // EU note for EURC
  if (isEurc) {
    doc.setFontSize(6)
    doc.setTextColor(...C.dim)
    doc.setFont('helvetica', 'normal')
    doc.text('Valuta di Riferimento: EUR · EURC (Circle) · Dir. 2013/34/UE', ml + 8, y + 34)
  }

  y += 44

  // ── Breakdown table ────────────────────────────────────────────────────
  const rows = [
    {
      label: 'Importo Netto (99.5%)',
      value: isEurc ? `€ ${p.netAmount}` : `${p.netAmount} ${p.symbol}`,
      accent: true,
    },
    {
      label: 'Commissione Gateway (0.5%)',
      value: isEurc ? `€ ${p.feeAmount}` : `${p.feeAmount} ${p.symbol}`,
      accent: false,
    },
    {
      label: 'Tipo Transazione',
      value: isEurc ? 'Euro Stablecoin (ERC-20)' : `Cripto Asset (${p.symbol})`,
      accent: false,
    },
  ]

  rows.forEach((row, i) => {
    const rowY = y + i * 9
    const isEven = i % 2 === 0
    if (isEven) {
      doc.setFillColor(...C.card2)
      doc.rect(ml, rowY, contentW, 9, 'F')
    }
    doc.setTextColor(...C.muted)
    doc.setFontSize(7)
    doc.setFont('helvetica', 'normal')
    doc.text(row.label, ml + 6, rowY + 6)

    if (row.accent) {
      doc.setTextColor(...C.em)
      doc.setFont('helvetica', 'bold')
    } else {
      doc.setTextColor(...C.text)
      doc.setFont('courier', 'normal')
    }
    doc.setFontSize(7)
    doc.text(row.value, W - mr - 6, rowY + 6, { align: 'right' })
  })

  y += rows.length * 9 + 4

  // ── Thin divider ───────────────────────────────────────────────────────
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.2)
  doc.line(ml, y, W - mr, y)
  y += 3

  // ── Parti dell'operazione ──────────────────────────────────────────────
  // Mittente
  doc.setTextColor(...C.dim)
  doc.setFontSize(6)
  doc.setFont('helvetica', 'bold')
  doc.text('MITTENTE (ORDINANTE)', ml, y)
  doc.setTextColor(...C.text)
  doc.setFontSize(7.5)
  doc.setFont('courier', 'normal')
  doc.text(p.sender, ml, y + 5)
  if (p.controparte?.name) {
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(...C.muted)
    doc.setFontSize(6)
    doc.text(
      p.controparte.name + (p.controparte.vatNumber ? `  ·  P.IVA: ${p.controparte.vatNumber}` : ''),
      ml, y + 9
    )
    y += 13
  } else {
    doc.setFont('helvetica', 'italic')
    doc.setTextColor(...C.dim)
    doc.setFontSize(5.5)
    doc.text('Identità non verificata — solo indirizzo blockchain noto', ml, y + 9)
    y += 12
  }

  // Destinatario
  doc.setTextColor(...C.dim)
  doc.setFontSize(6)
  doc.setFont('helvetica', 'bold')
  doc.text('DESTINATARIO (BENEFICIARIO)', ml, y)
  doc.setTextColor(...C.text)
  doc.setFontSize(7.5)
  doc.setFont('courier', 'normal')
  doc.text(p.recipient, ml, y + 5)

  const emiForRecipient = p.emittente || { legalName: 'RSend S.r.l.' }
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...C.muted)
  doc.setFontSize(6)
  doc.text(
    emiForRecipient.legalName + ('vatNumber' in emiForRecipient && emiForRecipient.vatNumber ? `  ·  P.IVA: ${emiForRecipient.vatNumber}` : ''),
    ml, y + 9
  )
  y += 13

  // ── MiCA Section ────────────────────────────────────────────────
  doc.setDrawColor(...C.border)
  doc.line(ml, y, W - mr, y)
  y += 3

  doc.setFillColor(...C.card)
  doc.roundedRect(ml, y, contentW, 22, 3, 3, 'F')
  doc.setDrawColor(...C.dim)
  doc.setLineWidth(0.3)
  doc.roundedRect(ml, y, contentW, 22, 3, 3, 'S')

  doc.setTextColor(...C.em)
  doc.setFontSize(6.5)
  doc.setFont('helvetica', 'bold')
  doc.text('DATI FISCALI (MiCA)', ml + 6, y + 6)

  const fiscalRows = [
    { key: 'payment_ref', val: p.paymentRef },
    { key: 'fiscal_ref',  val: p.fiscalRef },
  ]
  fiscalRows.forEach(({ key, val }, i) => {
    const fy = y + 12 + i * 6
    doc.setTextColor(...C.dim)
    doc.setFontSize(6)
    doc.setFont('courier', 'normal')
    doc.text(key, ml + 6, fy)
    doc.setTextColor(...C.text)
    doc.text(val.slice(0, 64), ml + 32, fy)
  })

  y += 27

  // ── EU Compliance badge (EURC only) ────────────────────────────────────
  if (isEurc) {
    doc.setFillColor(...C.euBlue)
    doc.roundedRect(ml, y, contentW, 14, 3, 3, 'F')

    doc.setTextColor(...C.euGold)
    doc.setFontSize(6)
    doc.setFont('helvetica', 'bold')
    doc.text('★  CONFORME AGLI STANDARD CONTABILI UE', ml + 6, y + 5)

    doc.setTextColor(180, 190, 230)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(5)
    doc.text(
      'Dir. 2013/34/UE (Contabilità) · Reg. UE 2023/1114 (MiCA)',
      ml + 6, y + 9,
    )
    doc.text(
      'Valuta: EUR · Token: EURC (Circle) · Nessuna conversione FX',
      ml + 6, y + 13,
    )
    y += 17
  }

  // ── QR Code + Verification Section ─────────────────────────────────────
  y += 2
  doc.setFillColor(...C.card)
  doc.roundedRect(ml, y, contentW, 28, 4, 4, 'F')
  doc.setDrawColor(...C.em)
  doc.setLineWidth(0.3)
  doc.roundedRect(ml, y, contentW, 28, 4, 4, 'S')

  // QR code image
  const qrSize = 20
  doc.addImage(qrDataUrl, 'PNG', ml + 4, y + 4, qrSize, qrSize)

  // Verification text
  const txLeft = ml + 4 + qrSize + 6
  doc.setTextColor(...C.em)
  doc.setFontSize(7)
  doc.setFont('helvetica', 'bold')
  doc.text('Verifica On-Chain', txLeft, y + 7)

  doc.setTextColor(...C.muted)
  doc.setFontSize(5.5)
  doc.setFont('helvetica', 'normal')
  doc.text('Scansiona il QR o visita il link per verificare la transazione:', txLeft, y + 12)

  doc.setTextColor(...C.emSoft)
  doc.setFontSize(5)
  doc.setFont('courier', 'normal')
  if (explorerUrl.length > 70) {
    doc.text(explorerUrl.slice(0, 70), txLeft, y + 17)
    doc.text(explorerUrl.slice(70), txLeft, y + 21)
  } else {
    doc.text(explorerUrl, txLeft, y + 17)
  }

  doc.setTextColor(...C.dim)
  doc.setFontSize(4.5)
  doc.text('Transazione immutabile e verificabile pubblicamente sulla blockchain.', txLeft, y + 25)

  y += 32

  // ── Hash di integrità documento ────────────────────────────────────
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

  doc.setFillColor(...C.card2)
  doc.roundedRect(ml, y, contentW, 10, 2, 2, 'F')
  doc.setTextColor(...C.dim)
  doc.setFontSize(5)
  doc.setFont('helvetica', 'bold')
  doc.text('HASH INTEGRITÀ DOCUMENTO (SHA-256)', ml + 4, y + 4)
  doc.setFont('courier', 'normal')
  doc.setFontSize(4)
  doc.setTextColor(...C.muted)
  doc.text(documentHash, ml + 4, y + 8)

  y += 13

  // ── Footer con disclaimer legale ───────────────────────────────────
  const footerH = 20
  doc.setFillColor(...C.card)
  doc.rect(0, H - footerH, W, footerH, 'F')
  doc.setFillColor(...C.em)
  doc.rect(0, H - footerH, W, 0.5, 'F')

  const emiFooter = p.emittente || { legalName: 'RSend S.r.l.', vatNumber: '' }
  doc.setTextColor(...C.dim)
  doc.setFontSize(5)
  doc.setFont('helvetica', 'normal')

  doc.text(
    `${emiFooter.legalName}${emiFooter.vatNumber ? '  ·  P.IVA ' + emiFooter.vatNumber : ''}  ·  rsend.io`,
    ml, H - footerH + 6
  )

  doc.setFontSize(4.5)
  doc.text(
    'Documento attestante operazione su blockchain. Non costituisce fattura ai sensi del DPR 633/72.',
    ml, H - footerH + 11
  )
  doc.text(
    'I valori in EUR sono indicativi e basati sul tasso riportato. Per fatturazione elettronica (SDI): compliance@rsend.io',
    ml, H - footerH + 15
  )

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
