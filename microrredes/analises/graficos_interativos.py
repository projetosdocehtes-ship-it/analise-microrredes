"""Gráfico HTML offline com inspeção por cursor das séries transitórias."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SERIES = (
    ("pv_kw", "FV", "kW", "#087e8b", "potencia"),
    ("carga_kw", "Carga", "kW", "#e69f00", "potencia"),
    ("bess_kw", "BESS (+ descarga)", "kW", "#009e73", "potencia"),
    ("rede_kw", "Rede (+ importação)", "kW", "#cc3344", "potencia"),
    ("soc", "SOC", "pu", "#8b5cf6", "soc"),
    ("tensao_pcc_pu", "Tensão PCC", "pu", "#2563eb", "tensao"),
    ("corrente_pcc_a", "Corrente PCC", "A", "#e76f51", "corrente"),
)


def gerar_html_interativo(resultado: dict[str, Any], destino: str | Path) -> str:
    """Salva todos os passos em um HTML autônomo para consulta offline."""
    serie = resultado["serie_temporal"]
    tempo = serie["tempo_s"]
    tamanho = len(tempo)
    if tamanho < 2:
        raise ValueError("A série temporal precisa de pelo menos dois pontos")
    valores: dict[str, list[float]] = {}
    for chave, *_ in SERIES:
        coluna = serie[chave]
        if len(coluna) != tamanho:
            raise ValueError(f"A série {chave} possui tamanho diferente do tempo")
        valores[chave] = [round(float(item), 7) for item in coluna]

    dados = {
        "passo_s": float(tempo[1] - tempo[0]),
        "n": tamanho,
        "inicio_falha_s": float(resultado["contingencia"]["inicio_s"]),
        "fim_falha_s": float(resultado["contingencia"]["fim_s"]),
        "series": valores,
        "metadados": [
            {"key": chave, "label": rotulo, "unit": unidade, "color": cor, "group": grupo}
            for chave, rotulo, unidade, cor, grupo in SERIES
        ],
    }
    payload = json.dumps(dados, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    payload = payload.replace("<", "\\u003c")
    html = _HTML.replace("__DADOS_SIMULACAO__", payload)
    caminho = Path(destino).expanduser().resolve()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(html, encoding="utf-8")
    return str(caminho)


_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transitório FV + BESS — inspeção interativa</title>
<style>
  :root { color-scheme: light; font-family: system-ui, sans-serif; }
  body { margin: 0; padding: 20px; color: #17212e; background: #f6f8fb; }
  main { max-width: 1180px; margin: auto; }
  h1 { font-size: 1.4rem; margin: 0 0 6px; }
  p { margin: 0 0 16px; color: #4d5c6c; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 12px; }
  button { border: 1px solid #b8c4d1; background: #fff; color: #17212e; border-radius: 6px; padding: 8px 12px; cursor: pointer; }
  button:hover { background: #edf2f7; }
  #cursor-readout { min-height: 26px; font-variant-numeric: tabular-nums; }
  .plot { background: #fff; border: 1px solid #d8e0e8; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
  .plot-title { margin: 0 0 2px 58px; font-weight: 600; }
  canvas { width: 100%; height: 165px; display: block; cursor: crosshair; touch-action: none; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 4px 58px; font-size: .9rem; }
  .swatch { display: inline-block; width: 18px; height: 3px; vertical-align: middle; margin-right: 4px; }
  .values { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 5px; min-height: 22px; font-variant-numeric: tabular-nums; font-size: .9rem; }
  .values span { white-space: nowrap; }
  .hint { font-size: .85rem; }
  @media (max-width: 600px) { body { padding: 10px; } canvas { height: 140px; } .plot-title, .legend { margin-left: 48px; } }
</style>
</head>
<body>
<main>
  <h1>Transitório FV + BESS</h1>
  <p>Arraste para ampliar um intervalo; use a roda para zoom e clique em “Visão completa” para voltar.</p>
  <div class="toolbar"><button id="reset" type="button">Visão completa</button><strong id="cursor-readout" aria-live="polite">Passe o cursor sobre um gráfico</strong></div>
  <section id="plots"></section>
  <p class="hint">Dados do modelo transitório reduzido. A faixa rosada marca a perda de strings FV.</p>
</main>
<script>
const data = __DADOS_SIMULACAO__;
const groups = [
  {id:'potencia', title:'Balanço de potência', axis:'Potência [kW]'},
  {id:'soc', title:'Estado de carga da bateria', axis:'SOC [pu]'},
  {id:'tensao', title:'Tensão no PCC', axis:'Tensão [pu]'},
  {id:'corrente', title:'Corrente no PCC', axis:'Corrente [A]'}
];
const finalTime = (data.n - 1) * data.passo_s;
let range = [0, finalTime];
let cursorTime = null;
let dragging = null;
const plots = document.getElementById('plots');
const panels = [];
for (const group of groups) {
  const section = document.createElement('section'); section.className = 'plot';
  const title = document.createElement('div'); title.className = 'plot-title'; title.textContent = group.title;
  const legend = document.createElement('div'); legend.className = 'legend';
  for (const s of data.metadados.filter(x => x.group === group.id)) {
    const item = document.createElement('span');
    const swatch = document.createElement('i'); swatch.className = 'swatch'; swatch.style.background = s.color;
    item.append(swatch, document.createTextNode(s.label)); legend.append(item);
  }
  const canvas = document.createElement('canvas'); canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', group.title + ': série temporal inspecionável pelo cursor');
  const values = document.createElement('div'); values.className = 'values';
  section.append(title, legend, canvas, values); plots.append(section);
  const panel = {group, canvas, values}; panels.push(panel);
  canvas.addEventListener('pointermove', event => onMove(event, panel));
  canvas.addEventListener('pointerleave', () => { if (!dragging) { cursorTime = null; drawAll(); updateValues(); } });
  canvas.addEventListener('pointerdown', event => { dragging = {panel, start: xToTime(event.offsetX, panel), end: xToTime(event.offsetX, panel)}; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointerup', event => {
    if (!dragging) return;
    dragging.end = xToTime(event.offsetX, panel);
    const a = Math.min(dragging.start, dragging.end), b = Math.max(dragging.start, dragging.end);
    if (b - a > data.passo_s * 5) range = [Math.max(0,a), Math.min(finalTime,b)];
    dragging = null; drawAll(); updateValues();
  });
  canvas.addEventListener('wheel', event => {
    event.preventDefault();
    const pivot = xToTime(event.offsetX, panel);
    const factor = event.deltaY > 0 ? 1.3 : 0.75;
    const width = Math.max(data.passo_s * 20, Math.min(finalTime, (range[1]-range[0]) * factor));
    const ratio = (pivot-range[0])/(range[1]-range[0]);
    let left = Math.max(0, Math.min(finalTime-width, pivot-width*ratio));
    range = [left, left+width]; drawAll(); updateValues();
  }, {passive:false});
}
document.getElementById('reset').addEventListener('click', () => { range=[0,finalTime]; drawAll(); updateValues(); });
new ResizeObserver(drawAll).observe(plots);
function geometry(panel) { const c = panel.canvas; return {left:58, right:c.clientWidth-12, top:8, bottom:c.clientHeight-28}; }
function xToTime(x,panel) { const g=geometry(panel); const fraction=Math.max(0,Math.min(1,(x-g.left)/(g.right-g.left))); return range[0]+fraction*(range[1]-range[0]); }
function timeToX(t,g) { return g.left+(t-range[0])/(range[1]-range[0])*(g.right-g.left); }
function nearestIndex(t) { return Math.max(0,Math.min(data.n-1,Math.round(t/data.passo_s))); }
function onMove(event,panel) { cursorTime=xToTime(event.offsetX,panel); if (dragging) dragging.end=cursorTime; drawAll(); updateValues(); }
function updateValues() {
  const label=document.getElementById('cursor-readout');
  if (cursorTime===null) { label.textContent='Passe o cursor sobre um gráfico'; for (const p of panels) p.values.textContent=''; return; }
  const i=nearestIndex(cursorTime), t=i*data.passo_s;
  const fault=t>=data.inicio_falha_s && t<data.fim_falha_s;
  label.textContent=`t = ${t.toFixed(5)} s · passo ${i}${fault ? ' · falha FV ativa' : ''}`;
  for (const p of panels) {
    p.values.replaceChildren();
    for (const s of data.metadados.filter(x=>x.group===p.group.id)) {
      const span=document.createElement('span'); span.textContent=`${s.label}: ${data.series[s.key][i].toFixed(s.unit==='pu'?6:3)} ${s.unit}`;
      span.style.color=s.color; p.values.append(span);
    }
  }
}
function drawAll() { for (const p of panels) draw(p); }
function draw(panel) {
  const c=panel.canvas, dpr=window.devicePixelRatio||1, w=c.clientWidth, h=c.clientHeight;
  if (w<=0 || h<=0) return;
  c.width=Math.round(w*dpr); c.height=Math.round(h*dpr);
  const ctx=c.getContext('2d'); ctx.scale(dpr,dpr); ctx.clearRect(0,0,w,h);
  const g=geometry(panel), width=g.right-g.left, height=g.bottom-g.top;
  const lines=data.metadados.filter(x=>x.group===panel.group.id);
  const first=Math.max(0,Math.floor(range[0]/data.passo_s)); const last=Math.min(data.n-1,Math.ceil(range[1]/data.passo_s));
  let min=Infinity,max=-Infinity;
  for (const s of lines) for (let i=first;i<=last;i++) { const v=data.series[s.key][i]; if (v<min) min=v; if (v>max) max=v; }
  if (panel.group.id==='soc') { min=Math.min(min,0); max=Math.max(max,1); }
  const pad=Math.max((max-min)*0.08, panel.group.id==='tensao'?0.0001:0.001); min-=pad; max+=pad;
  const y=v=>g.bottom-(v-min)/(max-min)*height;
  ctx.fillStyle='#fff'; ctx.fillRect(g.left,g.top,width,height);
  const faultLeft=Math.max(g.left,timeToX(data.inicio_falha_s,g)); const faultRight=Math.min(g.right,timeToX(data.fim_falha_s,g));
  if (faultRight>faultLeft) { ctx.fillStyle='rgba(220,53,69,0.13)'; ctx.fillRect(faultLeft,g.top,faultRight-faultLeft,height); }
  ctx.strokeStyle='#d8e0e8'; ctx.lineWidth=1; ctx.font='12px system-ui'; ctx.fillStyle='#506070';
  for (let k=0;k<=4;k++) {
    const yy=g.top+height*k/4; ctx.beginPath(); ctx.moveTo(g.left,yy); ctx.lineTo(g.right,yy); ctx.stroke();
    const val=max-(max-min)*k/4; ctx.textAlign='right'; ctx.fillText(val.toFixed(panel.group.id==='tensao'?4:panel.group.id==='soc'?2:1),g.left-7,yy+4);
  }
  for (let k=0;k<=5;k++) { const xx=g.left+width*k/5; ctx.beginPath();ctx.moveTo(xx,g.top);ctx.lineTo(xx,g.bottom);ctx.stroke();ctx.textAlign='center';ctx.fillText((range[0]+(range[1]-range[0])*k/5).toFixed(3),xx,h-7); }
  ctx.save();ctx.beginPath();ctx.rect(g.left,g.top,width,height);ctx.clip();
  const stride=Math.max(1,Math.floor((last-first)/Math.max(1,width*2)));
  for (const s of lines) {
    const arr=data.series[s.key]; ctx.beginPath(); ctx.strokeStyle=s.color; ctx.lineWidth=1.7;
    for (let i=first;i<=last;i+=stride) { const x=timeToX(i*data.passo_s,g), yy=y(arr[i]); if (i===first)ctx.moveTo(x,yy);else ctx.lineTo(x,yy); }
    ctx.lineTo(timeToX(last*data.passo_s,g),y(arr[last]));ctx.stroke();
  }
  if (cursorTime!==null && cursorTime>=range[0] && cursorTime<=range[1]) {
    const i=nearestIndex(cursorTime), x=timeToX(i*data.passo_s,g);
    ctx.strokeStyle='#223044';ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(x,g.top);ctx.lineTo(x,g.bottom);ctx.stroke();ctx.setLineDash([]);
    for (const s of lines) { ctx.beginPath();ctx.fillStyle=s.color;ctx.arc(x,y(data.series[s.key][i]),3.5,0,Math.PI*2);ctx.fill(); }
  }
  if (dragging && dragging.panel===panel) { const a=timeToX(dragging.start,g),b=timeToX(dragging.end,g);ctx.fillStyle='rgba(37,99,235,0.12)';ctx.fillRect(Math.min(a,b),g.top,Math.abs(b-a),height); }
  ctx.restore();
  ctx.strokeStyle='#a9b8c7';ctx.strokeRect(g.left,g.top,width,height);
}
drawAll();
</script>
</body>
</html>
"""
