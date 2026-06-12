#!/usr/bin/env python3
"""
patch_dashboard.py — Aplica correções NO no dashboard.py existente.

Uso:
    python patch_dashboard.py dashboard.py

Backups automaticamente antes de modificar.
"""
import sys, shutil, re
from datetime import datetime

if len(sys.argv) < 2:
    print("Uso: python patch_dashboard.py dashboard.py")
    sys.exit(1)

src_file = sys.argv[1]

# Backup
bak = src_file + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
shutil.copy(src_file, bak)
print(f"Backup: {bak}")

with open(src_file, encoding="utf-8") as f:
    src = f.read()

patches_ok = 0
patches_fail = 0

def patch(src, old, new, nome):
    global patches_ok, patches_fail
    if old in src:
        print(f"  OK  {nome}")
        patches_ok += 1
        return src.replace(old, new)
    else:
        print(f"  FALHOU  {nome}")
        patches_fail += 1
        return src

# ── PATCH 1: Brier correto para trades NO ────────────────────────────────────
src = patch(src,
    '''    brier_scores = [
        (float(t.get("model_prob") or 0) - (1.0 if t.get("result")=="WIN" else 0))**2
        for t in closed if t.get("model_prob") is not None
    ]''',
    '''    brier_scores = []
    for _t in closed:
        if _t.get("model_prob") is None:
            continue
        _prob_yes = float(_t.get("model_prob") or 0)
        _side = (_t.get("side") or "YES").upper()
        _outcome = 1.0 if _t.get("result") == "WIN" else 0.0
        # Para NO: probabilidade apostada é prob_no = 1 - prob_yes
        _prob_aposta = (1.0 - _prob_yes) if _side == "NO" else _prob_yes
        brier_scores.append((_prob_aposta - _outcome) ** 2)''',
    "Brier correto para NO"
)

# ── PATCH 2: Header tabela fechados — adicionar coluna Side ──────────────────
src = patch(src,
    '''        <thead><tr>
          <th></th><th>Cidade</th><th>Data</th><th>Target</th>
          <th>Stake</th><th>PnL</th><th>Prob</th><th>Mkt</th><th>Temp Real</th>
        </tr></thead>''',
    '''        <thead><tr>
          <th></th><th>Cidade</th><th>Data</th><th>Side</th><th>Target</th>
          <th>Stake</th><th>PnL</th><th>Prob</th><th>Entry</th><th>Temp Real</th>
        </tr></thead>''',
    "Header tabela fechados"
)

# ── PATCH 3: Linha tabela fechados — Side, prob correta, entry_price ─────────
src = patch(src,
    '''  cb.innerHTML=closed.map(t=>{
    const isWin=t.result==='WIN';
    const pnl=t.pnl||0;
    const temp=t.real_temp_c!=null?t.real_temp_c.toFixed(1)+'°C':'—';
    return`<tr>
      <td class="${isWin?'badge-win':'badge-loss'}" style="font-size:15px">${isWin?'✓':'✗'}</td>
      <td><span class="city-tag">${t.city||'—'}</span></td>
      <td>${t.market_date||'—'}</td>
      <td style="color:var(--muted)">${t.type||''} ${t.target||''}°${t.unit||'C'}</td>
      <td>$${(t.stake||0).toFixed(2)}</td>
      <td class="${pnl>=0?'badge-win':'badge-loss'}" style="font-weight:600">${pnl>=0?'+':''}$${Math.abs(pnl).toFixed(2)}</td>
      <td>${Math.round((t.model_prob||0)*100)}%</td>
      <td>${Math.round((t.market_price||0)*100)}%</td>
      <td style="color:var(--cyan)">${temp}</td>
    </tr>`}).join('');''',
    '''  cb.innerHTML=closed.map(t=>{
    const isWin=t.result==='WIN';
    const pnl=t.pnl||0;
    const temp=t.real_temp_c!=null?t.real_temp_c.toFixed(1)+'°C':'—';
    const side=t.side||'YES';
    const probAposta=side==='NO'?Math.round((1-(t.model_prob||0))*100):Math.round((t.model_prob||0)*100);
    const entryPct=Math.round((t.entry_price||t.market_price||0)*100);
    const sideClr=side==='NO'?'var(--amber)':'var(--cyan)';
    return`<tr>
      <td class="${isWin?'badge-win':'badge-loss'}" style="font-size:15px">${isWin?'✓':'✗'}</td>
      <td><span class="city-tag">${t.city||'—'}</span></td>
      <td>${t.market_date||'—'}</td>
      <td><b style="color:${sideClr}">${side}</b></td>
      <td style="color:var(--muted)">${t.type||''} ${t.target||''}°${t.unit||'C'}</td>
      <td>$${(t.stake||0).toFixed(2)}</td>
      <td class="${pnl>=0?'badge-win':'badge-loss'}" style="font-weight:600">${pnl>=0?'+':''}$${Math.abs(pnl).toFixed(2)}</td>
      <td>${probAposta}%</td>
      <td>${entryPct}%</td>
      <td style="color:var(--cyan)">${temp}</td>
    </tr>`}).join('');''',
    "Linha tabela fechados"
)

# ── PATCH 4: Header tabela abertos — adicionar Side ──────────────────────────
src = patch(src,
    '''        <thead><tr>
          <th>Cidade</th><th>Data</th><th>Tipo</th><th>Stake</th>
          <th>Prob Modelo</th><th>Mkt Price</th><th>Edge</th><th>Pergunta</th>
        </tr></thead>''',
    '''        <thead><tr>
          <th>Cidade</th><th>Data</th><th>Side</th><th>Tipo</th><th>Stake</th>
          <th>Prob Aposta</th><th>Entry</th><th>Edge</th><th>Pergunta</th>
        </tr></thead>''',
    "Header tabela abertos"
)

# ── PATCH 5: Linha tabela abertos — Side e entry_price ───────────────────────
src = patch(src,
    '''  ob.innerHTML=open.map(t=>{
    const prob=Math.round((t.model_prob||0)*100);
    const mkt=Math.round((t.market_price||0)*100);
    const edge=((t.edge||0)*100).toFixed(1);
    const cls=parseFloat(edge)>=0?'edge-pos':'edge-neg';
    return`<tr>
      <td><span class="city-tag">${t.city||'—'}</span></td>
      <td>${t.market_date||'—'}</td>
      <td style="color:var(--amber)">${t.type||'—'}</td>
      <td>$${(t.stake||0).toFixed(2)}</td>
      <td><div class="prob-bar-row"><div class="prob-bar-bg"><div class="prob-bar-fill" style="width:${prob}%"></div></div><span>${prob}%</span></div></td>
      <td>${mkt}%</td>
      <td class="${cls}">${parseFloat(edge)>=0?'+':''}${edge}%</td>
      <td style="color:var(--muted);font-size:11px">${(t.question||'').substring(0,50)}…</td>
    </tr>`}).join('');''',
    '''  ob.innerHTML=open.map(t=>{
    const side=t.side||'YES';
    const probAposta=side==='NO'?Math.round((1-(t.model_prob||0))*100):Math.round((t.model_prob||0)*100);
    const entryPct=Math.round((t.entry_price||t.market_price||0)*100);
    const edge=((t.edge||0)*100).toFixed(1);
    const cls=parseFloat(edge)>=0?'edge-pos':'edge-neg';
    const sideClr=side==='NO'?'var(--amber)':'var(--cyan)';
    return`<tr>
      <td><span class="city-tag">${t.city||'—'}</span></td>
      <td>${t.market_date||'—'}</td>
      <td><b style="color:${sideClr}">${side}</b></td>
      <td style="color:var(--amber)">${t.type||'—'}</td>
      <td>$${(t.stake||0).toFixed(2)}</td>
      <td><div class="prob-bar-row"><div class="prob-bar-bg"><div class="prob-bar-fill" style="width:${probAposta}%"></div></div><span>${probAposta}%</span></div></td>
      <td>${entryPct}%</td>
      <td class="${cls}">${parseFloat(edge)>=0?'+':''}${edge}%</td>
      <td style="color:var(--muted);font-size:11px">${(t.question||'').substring(0,50)}…</td>
    </tr>`}).join('');''',
    "Linha tabela abertos"
)

with open(src_file, "w", encoding="utf-8") as f:
    f.write(src)

print(f"\nResultado: {patches_ok} OK, {patches_fail} falha(s)")
if patches_fail == 0:
    print(f"dashboard.py atualizado com sucesso!")
else:
    print(f"ATENÇÃO: {patches_fail} patch(es) falharam — verifique manualmente")
    print(f"Backup disponível em: {bak}")
