// Same-origin when running locally; set the deployed URL printed by CDK (ApiUrl) for production.
const API = ["localhost", "127.0.0.1"].includes(location.hostname) ? "" : "REPLACE_WITH_API_URL";
let holdings = [];
const money = n => new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(n || 0);
async function load(prices=true) {
  const r = await fetch(`${API}/${prices ? "portfolio" : "holdings"}`); const d = await r.json();
  holdings = prices ? d.holdings : d;
  document.querySelector("#summary").textContent = prices ? `Value: ${money(d.totalValue)} · P/L: ${money(d.totalProfitLoss)}` : "Holdings loaded";
  if (prices) drawPie(holdings); else document.querySelector("#pie").innerHTML = "";
  document.querySelector("tbody").innerHTML = holdings.map((x,i)=>`<tr><td>${x.symbol}</td><td>${x.shares}</td><td>${money(x.cost)}</td><td>${prices?money(x.price):"—"}</td><td>${prices?money(x.value):"—"}</td><td>${prices?money(x.profitLoss):"—"}</td><td><button onclick="removeHolding(${i})">Delete</button></td></tr>`).join("");
}
const COLORS = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"];
function drawPie(rows) {
  const data = rows.filter(x => x.value > 0), total = data.reduce((s,x)=>s+x.value, 0);
  if (!total) { document.querySelector("#pie").innerHTML = "<p>No data</p>"; return; }
  const cx = 150, cy = 150, r = 100, pt = (a, d) => [cx + d*Math.cos(a), cy - d*Math.sin(a)];
  let a = 140 * Math.PI / 180, out = "";
  data.forEach((x, i) => {
    const frac = x.value / total, b = a - frac * 2 * Math.PI, color = COLORS[i % COLORS.length];
    if (frac > 0.9999) out += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${color}"/>`;
    else { const [x1,y1] = pt(a, r), [x2,y2] = pt(b, r); out += `<path d="M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${frac>0.5?1:0} 1 ${x2},${y2} Z" fill="${color}"/>`; }
    const m = (a + b) / 2, [lx,ly] = pt(m, r + 18), [px,py] = pt(m, r * 0.65);
    out += `<text x="${lx}" y="${ly}" text-anchor="middle">${x.symbol}</text><text x="${px}" y="${py}" text-anchor="middle" style="fill:white">${(frac*100).toFixed(1)}%</text>`;
    a = b;
  });
  document.querySelector("#pie").innerHTML = `<svg viewBox="0 0 300 300">${out}</svg>`;
}
async function save(){await fetch(`${API}/holdings`,{method:"PUT",headers:{"content-type":"application/json"},body:JSON.stringify(holdings)}); await load();}
document.querySelector("#form").onsubmit=async e=>{e.preventDefault(); let s=symbol.value.toUpperCase(), x={symbol:s,shares:+shares.value,cost:+cost.value}; let i=holdings.findIndex(h=>h.symbol===s); if(i<0) holdings.push(x); else holdings[i]=x; e.target.reset(); await save();};
async function removeHolding(i){holdings.splice(i,1); await save();} document.querySelector("#refresh").onclick=()=>load(); load();
