// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC20}          from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}       from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

error LengthMismatch();
error BadRecipientCount();
error BpsSumNot10000();
error ZeroRecipient();
error ZeroBps();
error ZeroAmount();
error ZeroToken();
error DuplicateRecipient();
error SelfRecipient();
error NoPolicy();
error BelowMinAmount(uint256 amount, uint256 minAmount);

/// RSendsAutoSplit — distribuzione periodica non-custodial del saldo di un
/// wallet merchant dedicato. Il merchant approva UNA volta
/// (token.approve(autoSplit, MAX)) e registra una policy (2..10 destinatari,
/// bps a somma ESATTA 10000, minAmount). executeSplit è permissionless:
/// chiunque (keeper incluso) distribuisce min(balance, allowance) via
/// transferFrom merchant -> recipient[i], tutto-o-niente, e con allowance MAX
/// il wallet chiude a saldo ESATTAMENTE zero — salvo le due condizioni nelle
/// NOTE in fondo, che sono i soli modi noti di romperlo: un token non standard
/// (non difendibile on-chain) e un leg verso il merchant stesso (ora rifiutato
/// in setPolicy). Revoca unilaterale: approve(0).
/// Nessun owner, pause, upgrade, delegatecall o call arbitraria: il contratto
/// non detiene mai saldo e nessun ruolo privilegiato esiste.
///
/// NOTA resto: qui il resto della divisione intera va all'ULTIMO recipient
/// (amount - somma dei floor precedenti), NON al primo come in
/// RSendsSplitRouter/_computeAmounts. Questa matematica NON va replicata via
/// split_math.py — quel modulo rispecchia il SOLO SplitRouter.
///
/// NOTA token: setPolicy accetta QUALUNQUE address ERC-20 e il contratto non
/// può difendersi da un token non standard. Con un token fee-on-transfer o
/// rebasing l'invariante saldo-a-zero NON regge: balanceOf scende più di
/// quanto trasferito e il resto sull'ultima leg non chiude. L'invariante vale
/// solo per ERC-20 standard senza fee-on-transfer/rebasing; l'unico token
/// supportato è USDC su Base. L'enforcement è responsabilità del CHIAMANTE:
/// il backend deve rifiutare setPolicy per token assenti dal registry
/// (token_registry.json) e la UI non deve mai esporre un campo token address
/// libero.
///
/// NOTA self-recipient: un leg verso il merchant stesso rompe la STESSA
/// invariante per una via diversa dal token. transferFrom(merchant, merchant, X)
/// è un self-transfer valido: il saldo scende di X e risale di X, cioè non
/// scende affatto, e il residuo finale è ESATTAMENTE quel leg — qualunque
/// posizione occupi nell'array (il residuo vale sempre amounts[m], perché gli
/// amounts sommano a total). L'ultima posizione è solo il caso peggiore: la
/// regola del resto le assegna anche il dust.
/// Il danno però non si ferma all'invariante. executeSplit è permissionless e
/// senza cooldown, quindi ogni chiamata successiva ri-splitta quel residuo e la
/// quota del merchant si erode a favore degli altri destinatari: 1000 a
/// 50/30/20 col merchant in ultima posizione fa 500/300/200 alla prima
/// chiamata e 625/374/1 dopo cinque. Non serve un attaccante — è la normale
/// cadenza del keeper; un co-destinatario può accelerarla e ci guadagna.
/// Per questo setPolicy rifiuta msg.sender tra i recipients (SelfRecipient).
/// A differenza della NOTA token, qui l'enforcement è ON-CHAIN e non delegato
/// al chiamante: il backend non costruisce policy (recipients e bps li firma il
/// merchant con la propria chiave), quindi non avrebbe nulla da validare.
///
/// Il fix NON è retroattivo. Il contratto è immutabile e non ha migrazione: una
/// policy già registrata su un'ISTANZA PRECEDENTE — qualunque deploy anteriore
/// all'introduzione di SelfRecipient — conserva il vecchio comportamento per
/// sempre, e nessuna chiamata a questa istanza la corregge. Solo le
/// registrazioni fatte su QUESTO bytecode sono protette; le policy vive su
/// deploy anteriori vanno riscritte dal merchant contro la nuova istanza. Chi
/// legge lo stato on-chain di una registrazione (pannello dashboard) dovrebbe
/// segnalare un leg che paga il source wallet stesso: è il caso che questo
/// contratto non può più creare ma che gli indirizzi vecchi possono ancora
/// contenere.
contract RSendsAutoSplit is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant MIN_RECIPIENTS = 2;
    uint256 public constant MAX_RECIPIENTS = 10;
    uint256 public constant BPS_DENOMINATOR = 10_000;

    struct Policy {
        address[] recipients;
        uint16[] bps;
        uint256 minAmount;
    }

    /// L'unica scrittura passa da setPolicy/clearPolicy con chiave
    /// msg.sender: nessuno può toccare la policy di un altro merchant.
    mapping(address merchant => mapping(address token => Policy)) private _policies;

    event PolicySet(
        address indexed merchant, address indexed token,
        address[] recipients, uint16[] bps, uint256 minAmount
    );
    event PolicyCleared(address indexed merchant, address indexed token);
    event SplitExecuted(
        address indexed merchant, address indexed token, address indexed caller,
        uint256 totalAmount, address[] recipients, uint256[] amounts, uint256 blockTimestamp
    );

    /// Registra (o sostituisce integralmente) la policy di msg.sender per
    /// `token`. Valida forma e somma; i duplicati sono rifiutati perché una
    /// leg doppia è quasi certamente un errore di configurazione.
    ///
    /// msg.sender NON può comparire tra i recipients (SelfRecipient): pagarsi
    /// da solo è un self-transfer in esecuzione, il saldo non scende e ogni
    /// chiamata successiva di executeSplit ri-splitta il residuo — v. NOTA
    /// self-recipient in testa al file per la matematica e per la
    /// non-retroattività su istanze precedenti.
    /// Errore DEDICATO e non DuplicateRecipient: in una policy del genere non
    /// c'è nulla di duplicato, e il nome sbagliato manderebbe chi lo incontra a
    /// cercare un indirizzo ripetuto che non esiste.
    /// La regola è contro msg.sender, non contro una lista globale: un ALTRO
    /// merchant può legittimamente pagare questo indirizzo.
    /// Questo è anche l'UNICO punto in cui la regola si può applicare: in
    /// executeSplit il self-transfer è un'operazione ERC-20 legittima, e
    /// rifiutarlo lì impedirebbe per sempre di splittare a chi una policy così
    /// ce l'ha già.
    function setPolicy(
        address token, address[] calldata recipients, uint16[] calldata bps, uint256 minAmount
    ) external {
        if (token == address(0)) revert ZeroToken();
        uint256 n = recipients.length;
        if (n != bps.length) revert LengthMismatch();
        if (n < MIN_RECIPIENTS || n > MAX_RECIPIENTS) revert BadRecipientCount();

        uint256 bpsSum;
        for (uint256 i; i < n; ++i) {
            address to = recipients[i];
            if (to == address(0)) revert ZeroRecipient();
            // Un leg verso il merchant è un self-transfer: il saldo non scende
            // e il resto NON chiude a zero (v. invariante in testa al file).
            if (to == msg.sender) revert SelfRecipient();
            if (bps[i] == 0) revert ZeroBps();
            bpsSum += bps[i];
            for (uint256 j = i + 1; j < n; ++j) {
                if (recipients[j] == to) revert DuplicateRecipient();
            }
        }
        if (bpsSum != BPS_DENOMINATOR) revert BpsSumNot10000();

        Policy storage p = _policies[msg.sender][token];
        p.recipients = recipients; // calldata->storage copy replaces, shrink included
        p.bps = bps;
        p.minAmount = minAmount;

        emit PolicySet(msg.sender, token, recipients, bps, minAmount);
    }

    /// Rimuove la policy di msg.sender per `token`. Idempotente.
    function clearPolicy(address token) external {
        delete _policies[msg.sender][token];
        emit PolicyCleared(msg.sender, token);
    }

    /// Permissionless: distribuisce min(balance, allowance) del merchant
    /// secondo la sua policy. Ogni leg è un safeTransferFrom diretto
    /// merchant -> recipient: se UNA fallisce (es. blacklist USDC), l'intera
    /// esecuzione reverte — mai una distribuzione parziale.
    function executeSplit(address merchant, address token) external nonReentrant {
        Policy storage p = _policies[merchant][token];
        (uint256 total, uint256[] memory amounts) = _plan(p, merchant, token);

        uint256 n = p.recipients.length;
        address[] memory plain = new address[](n); // per l'evento, snapshot della policy
        for (uint256 i; i < n; ++i) {
            address to = p.recipients[i];
            plain[i] = to;
            IERC20(token).safeTransferFrom(merchant, to, amounts[i]);
        }
        emit SplitExecuted(merchant, token, msg.sender, total, plain, amounts, block.timestamp);
    }

    function getPolicy(address merchant, address token)
        external view
        returns (address[] memory recipients, uint16[] memory bps, uint256 minAmount)
    {
        Policy storage p = _policies[merchant][token];
        return (p.recipients, p.bps, p.minAmount);
    }

    /// Pre-flight per il keeper: stessi guard e stessa matematica di
    /// executeSplit (reverte NoPolicy/ZeroAmount/BelowMinAmount), così una
    /// eth_call che passa qui è una executeSplit che non brucia gas invano.
    function previewSplit(address merchant, address token)
        external view
        returns (uint256 total, uint256[] memory amounts)
    {
        return _plan(_policies[merchant][token], merchant, token);
    }

    /// Guard comuni + calcolo importi: floor division per leg, resto
    /// all'ULTIMA — così sum(amounts) == total e il wallet chiude a zero.
    function _plan(Policy storage p, address merchant, address token)
        private view
        returns (uint256 total, uint256[] memory amounts)
    {
        uint256 n = p.recipients.length;
        if (n == 0) revert NoPolicy();

        uint256 balance = IERC20(token).balanceOf(merchant);
        uint256 allowance = IERC20(token).allowance(merchant, address(this));
        total = balance < allowance ? balance : allowance;
        if (total == 0) revert ZeroAmount();
        if (total < p.minAmount) revert BelowMinAmount(total, p.minAmount);

        amounts = new uint256[](n);
        uint256 allocated;
        for (uint256 i; i < n - 1; ++i) {
            uint256 amt = (total * p.bps[i]) / BPS_DENOMINATOR;
            amounts[i] = amt;
            allocated += amt;
        }
        amounts[n - 1] = total - allocated;
    }
}
