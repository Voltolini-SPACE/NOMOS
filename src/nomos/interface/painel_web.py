"""NOMOS interface.painel_web — Painel 4.0: o cockpit local do NOMOS.

Layout de aplicativo (sidebar de navegação · conteúdo · rail de status),
inspirado em painéis de agente modernos, com a marca NOMOS congelada.

Princípios:
- escuta EXCLUSIVAMENTE em 127.0.0.1 (qualquer outro bind é recusado);
- URL com segmento secreto aleatório — sem ele, 404 para tudo;
- LER é livre; AGIR existe em DUAS portas governadas (MC38):
  1. ``aprovacoes/decidir`` — token SINGLE-USE da fila (kernel.approvals,
     TTL 5 min, comparação em tempo constante, tudo auditado);
  2. ``chat/enviar`` — chat LOCAL (token CSRF por servidor; roda só motor
     local, fail-closed sem motor, cada turno auditado; nuvem só no terminal).
  Qualquer outro POST é 405. Sem fila, aprovações somem; com ``--sem-chat``
  ou sem chat habilitado, o chat vira histórico read-only;
- HTML autossuficiente: zero assets externos, zero JavaScript de terceiros
  (o único <script> é nosso, inline, sem rede: scrollspy/filtro/relógio);
- headers de segurança em toda resposta (CSP restritiva, nosniff,
  no-referrer, no-store);
- mostra metadados — nunca conteúdo sensível (a auditoria já redige na
  entrada; títulos de conversa passam por redact_text; corpo NUNCA aparece).
"""
from __future__ import annotations

import contextlib
import html
import json
import platform as _plataforma
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

# ---------------------------------------------------------------------------
# identidade visual — paleta da marca CONGELADA (brandbook v1.0)
# ---------------------------------------------------------------------------
_CSS = """
 /* tema ESCURO (padrão) — brandbook congelado */
 :root{--bg:#0A0F0D;--surface:#111814;--surface2:#0d1411;--line:#1d2a22;
   --neon:#5AF78E;--dim:#2BD968;--txt:#E8FFE8;--fraco:#7c9a84;
   --rosa:#FF5FA2;--ciano:#56E1E9;--amarelo:#F2C14E;--vermelho:#FF5C57;
   --glow:0 0 8px rgba(90,247,142,.45)}
 /* tema CLARO — mesma marca, contraste WCAG AA (verificado) */
 :root[data-tema="claro"]{
   --bg:#f4f7f4;--surface:#ffffff;--surface2:#eaf0ea;--line:#b9c8bc;
   --neon:#0b7a3b;--dim:#0b7a3b;--txt:#10261a;--fraco:#3f6b50;
   --rosa:#b3266e;--ciano:#0a6d74;--amarelo:#8a6a12;--vermelho:#b3261e;
   --glow:none}
 /* sem escolha explícita, respeita o SO */
 @media (prefers-color-scheme:light){:root:not([data-tema]){
   --bg:#f4f7f4;--surface:#ffffff;--surface2:#eaf0ea;--line:#b9c8bc;
   --neon:#0b7a3b;--dim:#0b7a3b;--txt:#10261a;--fraco:#3f6b50;
   --rosa:#b3266e;--ciano:#0a6d74;--amarelo:#8a6a12;--vermelho:#b3261e;
   --glow:none}}
 *{box-sizing:border-box}
 html{scroll-behavior:smooth}
 @media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
 body{font-family:'JetBrains Mono','IBM Plex Mono','SF Mono',Menlo,Consolas,
   monospace;background:var(--bg);color:var(--txt);margin:0;line-height:1.5;
   font-size:14px}
 a{color:var(--ciano)}
 .skip{position:absolute;left:-999px;top:0;background:var(--neon);
   color:var(--bg);padding:.4rem .8rem;z-index:99}
 .skip:focus{left:0}
 :focus-visible{outline:2px solid var(--neon);outline-offset:2px}

 /* ---- app shell: sidebar de abas | conteúdo (rail eliminado no MC37) ---- */
 .app{display:grid;grid-template-columns:210px minmax(0,1fr);
   min-height:100vh}
 .sidebar{background:var(--surface2);border-right:1px solid var(--line);
   padding:1rem .9rem;position:sticky;top:0;height:100vh;overflow:auto}
 .main{padding:0 1.4rem 3rem;min-width:0}
 @media(max-width:820px){.app{display:block}
   .sidebar{position:static;height:auto;border-right:0;
     border-bottom:1px solid var(--line)}}

 /* ---- abas: só a ativa aparece (menos densidade; navegação clara) ---- */
 .aba{display:none}
 .aba.ativa{display:block}
 /* ao filtrar, o JS revela tudo (.buscando) p/ a busca varrer todas as abas */
 .app.buscando .aba{display:block}

 /* ---- sidebar ---- */
 .brand{color:var(--neon);text-shadow:var(--glow);font-weight:700;
   font-size:1.15rem;letter-spacing:.18em}
 .brand .cursor{animation:pisca 1.2s steps(1) infinite}
 @keyframes pisca{50%{opacity:0}}
 @media (prefers-reduced-motion:reduce){.brand .cursor{animation:none}}
 .tagline{color:var(--fraco);font-size:.72rem;margin:.15rem 0 1.1rem}
 nav.menu{display:flex;flex-direction:column;gap:.15rem}
 nav.menu a{color:var(--fraco);text-decoration:none;font-size:.82rem;
   padding:.42rem .6rem;border-radius:6px;border-left:2px solid transparent;
   display:flex;align-items:center;gap:.55rem}
 nav.menu a:hover{color:var(--txt);background:var(--surface)}
 nav.menu a.ativo{color:var(--neon);border-left-color:var(--neon);
   background:var(--surface)}
 nav.menu .ico{width:1.1em;text-align:center;opacity:.85}
 .badge{color:var(--bg);background:var(--neon);border-radius:10px;
   padding:0 .4rem;font-size:.72rem;margin-left:auto;font-weight:700}
 .badge.alerta{background:var(--amarelo)}
 /* mini-nav de saltos dentro da aba (some no mobile p/ não poluir) */
 .subnav{margin:.2rem 0 1rem;font-size:.72rem;color:var(--fraco);
   display:flex;flex-wrap:wrap;gap:.1rem .8rem}
 .subnav a{color:var(--fraco);text-decoration:none}
 .subnav a:hover{color:var(--neon)}

 /* ---- bloco Sistema (rodapé da sidebar) ---- */
 .sysbox{margin-top:1.2rem;border-top:1px solid var(--line);
   padding-top:.8rem;font-size:.7rem;color:var(--fraco)}
 .sysbox b{color:var(--txt)}
 .chip{display:inline-block;border-radius:4px;padding:.05rem .45rem;
   font-size:.72rem;font-weight:700}
 .chip.ok{background:rgba(90,247,142,.15);color:var(--neon)}
 .chip.warn{background:rgba(242,193,78,.15);color:var(--amarelo)}
 .chip.err{background:rgba(255,92,87,.15);color:var(--vermelho)}
 .sysbox .linha{margin:.22rem 0}

 /* ---- topo do conteúdo ---- */
 .topo{position:sticky;top:0;z-index:9;background:rgba(10,15,13,.94);
   backdrop-filter:blur(6px);border-bottom:1px solid var(--line);
   padding:.75rem 0 .6rem;margin-bottom:.6rem}
 h1{font-size:1.2rem;margin:0;color:var(--neon);text-shadow:var(--glow)}
 h1 .lock{color:var(--dim);font-size:.9rem}
 .sub{color:var(--fraco);font-size:.72rem;margin:.2rem 0 0}
 .acoes{display:flex;gap:.6rem;align-items:center;margin-top:.5rem;
   flex-wrap:wrap}
 .acoes input{background:var(--surface);border:1px solid #4f7660;
   color:var(--txt);border-radius:6px;padding:.3rem .6rem;font:inherit;
   font-size:.76rem;width:230px;max-width:60vw}
 .acoes a{font-size:.72rem;color:var(--fraco)}
 .acoes a:hover{color:var(--neon)}
 .acoes a.ativo{color:var(--neon)}
 .acoes button{font:inherit;font-size:.72rem;border-radius:6px;
   padding:.3rem .7rem;cursor:pointer;border:1px solid #4f7660;
   background:var(--surface2);color:var(--txt)}
 .acoes button:hover{border-color:var(--dim);color:var(--neon)}
 #filtro-n{font-size:.72rem;color:var(--fraco)}

 /* ---- seções ---- */
 h2{font-size:.82rem;text-transform:uppercase;letter-spacing:.14em;
   color:var(--dim);margin:2.1rem 0 .7rem;border-left:3px solid var(--neon);
   padding-left:.6rem;scroll-margin-top:5.5rem}
 h2::before{content:"// ";color:var(--fraco)}
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));
   gap:1px;background:var(--line);border:1px solid var(--line);
   border-radius:8px;overflow:hidden;margin:1rem 0 .4rem}
 .kpi{background:var(--surface);padding:.7rem .8rem}
 .kpi b{display:block;color:var(--neon);font-size:1.12rem;
   text-shadow:var(--glow)}
 .kpi span{color:var(--fraco);font-size:.72rem}
 .card{background:var(--surface);border:1px solid var(--line);
   border-radius:8px;padding:.75rem .95rem;margin:.55rem 0}
 .card.ok{border-left:4px solid var(--neon)}
 .card.warn{border-left:4px solid var(--amarelo)}
 .card.err{border-left:4px solid var(--vermelho)}
 small{color:var(--fraco)}
 b{color:var(--txt)}
 code,.k{background:#0c1410;color:var(--neon);padding:.08rem .35rem;
   border-radius:4px;border:1px solid var(--line)}
 table{border-collapse:collapse;width:100%;font-size:.82rem}
 td,th{padding:.32rem .55rem;text-align:left;border-bottom:1px solid
   var(--line)}
 th{color:var(--fraco);font-weight:normal;text-transform:uppercase;
   font-size:.72rem;letter-spacing:.1em}
 .pill{display:inline-block;border:1px solid var(--line);border-radius:20px;
   padding:.05rem .55rem;font-size:.7rem;color:var(--fraco);
   margin-right:.3rem}
 .pill.local{color:var(--neon);border-color:var(--dim)}
 .pill.nuvem{color:var(--amarelo);border-color:#4a3f1e}

 /* ---- aprovações (única porta de ação) ---- */
 .aprov{border-left:4px solid var(--amarelo)}
 .aprov .alvo{color:var(--ciano);word-break:break-all}
 .aprov form{display:inline}
 .aprov button{font:inherit;font-size:.78rem;border-radius:6px;
   padding:.35rem .9rem;cursor:pointer;border:1px solid var(--line);
   background:var(--surface2);color:var(--txt);margin:.4rem .5rem 0 0}
 .aprov button.sim{border-color:var(--dim);color:var(--neon)}
 .aprov button.sim:hover{background:rgba(90,247,142,.12)}
 .aprov button.nao{border-color:#5a2b29;color:var(--vermelho)}
 .aprov button.nao:hover{background:rgba(255,92,87,.12)}
 .conta{color:var(--amarelo)}

 /* ---- blocos "ao vivo" (na visão geral; antes eram o rail) ---- */
 .mini-h{font-size:.72rem;text-transform:uppercase;letter-spacing:.14em;
   color:var(--fraco);margin:.2rem 0 .5rem;border:0;padding:0}
 .mini{background:var(--surface);border:1px solid var(--line);
   border-radius:8px;padding:.5rem .6rem;font-size:.74rem;margin:.3rem 0}
 .mini b{color:var(--neon);font-weight:700}
 .colunas2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
 @media(max-width:640px){.colunas2{grid-template-columns:1fr}}
 ul.lista{margin:.4rem 0 0;padding-left:1.1rem}
 ul.lista li{margin:.2rem 0;font-size:.82rem}
 /* ---- chat estilo ChatGPT (MC38): histórico | thread + composer ---- */
 .chat-wrap{display:grid;grid-template-columns:230px minmax(0,1fr);gap:1rem;
   margin-top:.6rem}
 @media(max-width:720px){.chat-wrap{grid-template-columns:1fr}}
 .chat-hist{border:1px solid var(--line);border-radius:8px;background:
   var(--surface);padding:.5rem;max-height:60vh;overflow:auto}
 .chat-hist a{display:block;color:var(--fraco);text-decoration:none;
   font-size:.76rem;padding:.35rem .5rem;border-radius:6px;
   border-left:2px solid transparent;word-break:break-word}
 .chat-hist a:hover{color:var(--txt);background:var(--surface2)}
 .chat-hist a.aberta{color:var(--neon);border-left-color:var(--neon);
   background:var(--surface2)}
 .chat-hist .nova{color:var(--neon);border:1px dashed var(--dim);
   text-align:center;margin-bottom:.4rem}
 .chat-thread{border:1px solid var(--line);border-radius:8px;background:
   var(--surface);padding:.9rem;min-height:200px;display:flex;
   flex-direction:column;gap:.6rem}
 .bolha{max-width:82%;padding:.55rem .8rem;border-radius:12px;font-size:.86rem;
   line-height:1.5;white-space:pre-wrap;word-break:break-word}
 .bolha.user{align-self:flex-end;background:var(--dim);color:var(--bg);
   border-bottom-right-radius:3px}
 .bolha.assistant{align-self:flex-start;background:var(--surface2);
   border:1px solid var(--line);border-bottom-left-radius:3px}
 .bolha.note{align-self:center;background:transparent;color:var(--amarelo);
   font-size:.78rem;border:1px dashed #4a3f1e;max-width:100%}
 .bolha .quem{display:block;font-size:.66rem;opacity:.7;margin-bottom:.15rem}
 .chat-vazio{color:var(--fraco);font-size:.84rem;margin:auto}
 .composer{display:flex;gap:.5rem;margin-top:.2rem}
 .composer textarea{flex:1;background:var(--surface2);color:var(--txt);
   border:1px solid #4f7660;border-radius:8px;padding:.5rem .7rem;font:inherit;
   font-size:.84rem;resize:vertical;min-height:2.6rem}
 .composer button{font:inherit;font-size:.84rem;border-radius:8px;
   padding:.4rem 1.1rem;cursor:pointer;border:1px solid var(--dim);
   background:var(--surface2);color:var(--neon);align-self:flex-end}
 .composer button:hover{background:rgba(90,247,142,.12)}
 .chat-nota{color:var(--fraco);font-size:.72rem;margin:.4rem 0 0}

 /* recolhíveis: detalhe dá acesso sem poluir (fecha por padrão) */
 details.mais{margin:.6rem 0}
 details.mais>summary{cursor:pointer;color:var(--dim);font-size:.8rem;
   padding:.2rem 0;list-style:none}
 details.mais>summary::-webkit-details-marker{display:none}
 details.mais>summary::before{content:"▸ ";color:var(--fraco)}
 details.mais[open]>summary::before{content:"▾ "}
 footer{border-top:1px solid var(--line);margin-top:2.5rem;padding:1rem 0;
   color:var(--fraco);font-size:.72rem}

 /* mobile: abas viram pills em linha (fim da folha p/ vencer a cascata) */
 @media(max-width:820px){
   nav.menu{flex-direction:row;flex-wrap:wrap;gap:.15rem .3rem}
   nav.menu a{border:1px solid var(--line);border-radius:16px;
     padding:.28rem .7rem}
   nav.menu .badge{margin-left:.35rem}
   .sysbox{display:flex;flex-wrap:wrap;gap:.1rem .9rem}}
"""

# JavaScript próprio, inline, sem rede: melhoria progressiva apenas.
_JS = """
(function(){
 'use strict';
 var app=document.querySelector('.app');
 // ---- tema claro/escuro: respeita o SO; escolha explícita persiste
 var root=document.documentElement;
 function temaAtual(){
   var t=root.getAttribute('data-tema');
   if(t)return t;
   return (window.matchMedia&&window.matchMedia('(prefers-color-scheme:light)').matches)
     ?'claro':'escuro';
 }
 try{var salvo=localStorage.getItem('nomos-tema');
   if(salvo==='claro'||salvo==='escuro')root.setAttribute('data-tema',salvo);
 }catch(e){}
 var tbtn=document.getElementById('tema-btn');
 function pintaBtn(){
   if(!tbtn)return;
   var claro=temaAtual()==='claro';
   // rótulo mostra o ALVO do clique (◐ = glifo que renderiza em toda fonte)
   tbtn.textContent=claro?'◐ escuro':'◐ claro';
   tbtn.setAttribute('aria-label',
     claro?'mudar para tema escuro':'mudar para tema claro');
   tbtn.setAttribute('aria-pressed',claro?'true':'false');
 }
 pintaBtn();
 if(tbtn){tbtn.addEventListener('click',function(){
   var novo=temaAtual()==='claro'?'escuro':'claro';
   root.setAttribute('data-tema',novo);
   try{localStorage.setItem('nomos-tema',novo);}catch(e){}
   pintaBtn();
 });}
 // ---- abas: mostra UMA por vez (menos densidade); deep-link ativa a certa
 var tabs=[].slice.call(document.querySelectorAll('nav.menu a[data-aba]'));
 var abas=[].slice.call(document.querySelectorAll('.aba'));
 // mapa âncora(#id de h2) -> aba que a contém, p/ deep-links continuarem valendo
 var secaoDaAba={};
 abas.forEach(function(ab){
   ab.querySelectorAll('[id]').forEach(function(el){
     secaoDaAba[el.id]=ab.getAttribute('data-aba');});});
 function mostrar(nome,foco){
   if(!nome) nome=(abas[0]&&abas[0].getAttribute('data-aba'));
   abas.forEach(function(ab){
     ab.classList.toggle('ativa',ab.getAttribute('data-aba')===nome);});
   tabs.forEach(function(t){
     t.classList.toggle('ativo',t.getAttribute('data-aba')===nome);});
   if(foco){var alvo=document.getElementById(foco);
     if(alvo&&alvo.scrollIntoView)alvo.scrollIntoView({block:'start'});}
 }
 tabs.forEach(function(t){
   t.addEventListener('click',function(ev){
     ev.preventDefault();
     var nome=t.getAttribute('data-aba');
     mostrar(nome);
     if(history.replaceState)history.replaceState(null,'','#'+nome);
   });});
 // qualquer link #secao (subnav, avisos) troca de aba e rola até a seção
 document.addEventListener('click',function(ev){
   var a=ev.target.closest&&ev.target.closest('a[href^="#"]');
   if(!a||a.hasAttribute('data-aba'))return;
   var id=a.getAttribute('href').slice(1);
   if(secaoDaAba[id]){ev.preventDefault();mostrar(secaoDaAba[id],id);
     if(history.replaceState)history.replaceState(null,'','#'+id);}
 });
 // estado inicial: hash aponta p/ aba OU p/ uma seção dentro de uma aba
 (function(){var h=(location.hash||'').slice(1);
   if(secaoDaAba[h])mostrar(secaoDaAba[h],h);
   else mostrar(h||null);})();

 // filtro rápido: com texto, revela TODAS as abas e varre tudo; ao limpar,
 // o CSS volta sozinho a mostrar só a aba ativa (.aba.ativa)
 var f=document.getElementById('filtro');
 if(f){f.addEventListener('input',function(){
   var q=f.value.toLowerCase(),vis=0,tot=0;
   if(app)app.classList.toggle('buscando',!!q);
   document.querySelectorAll('.filtravel').forEach(function(el){
     var mostra=el.textContent.toLowerCase().indexOf(q)>=0;
     el.style.display=mostra?'':'none';
     tot+=1;if(mostra)vis+=1;});
   var n=document.getElementById('filtro-n');
   if(n)n.textContent=q?(vis+' de '+tot+' itens'):'';
 });}
 // contagem regressiva das aprovações (expiram sozinhas em 5 min);
 // em 0, os botões são desabilitados — clicar só renderia um 409
 function tique(){
  document.querySelectorAll('[data-expira]').forEach(function(el){
    var s=Math.max(0,Math.round(+el.getAttribute('data-expira')-Date.now()/1000));
    el.textContent=s>0?(Math.floor(s/60)+'m'+('0'+s%60).slice(-2)+'s')
                      :'expirada — recarregue';
    if(s<=0){var card=el.closest('.aprov');
      if(card){card.querySelectorAll('button').forEach(function(b){
        b.disabled=true;});}}});
 }
 tique(); setInterval(tique,1000);
 // auto-recarregar OPT-IN (?refresh=N) em JS, cancelável: pausa enquanto
 // você filtra ou há aprovação na tela (o antigo meta refresh recarregava
 // no meio da decisão e apagava o filtro digitado)
 var mr=document.querySelector('meta[name="nomos-refresh"]');
 if(mr){
  var total=parseInt(mr.getAttribute('content'),10)||0,resta=total;
  var st=document.getElementById('auto-estado');
  if(total>0){setInterval(function(){
    var ocupado=(f&&(f.value||document.activeElement===f))
                ||document.querySelector('.aprov [data-expira]');
    if(ocupado){if(st)st.textContent='auto: pausado';return;}
    resta-=1;
    if(st)st.textContent='auto: '+resta+'s';
    if(resta<=0){location.reload();}
  },1000);}
 }
 // relógio local no bloco Sistema
 var rel=document.getElementById('relogio');
 if(rel){rel.textContent=new Date().toLocaleTimeString();
   setInterval(function(){
     rel.textContent=new Date().toLocaleTimeString();},1000);}
})();
"""

# headers enviados em TODAS as respostas do painel (defesa em profundidade)
_HEADERS_SEGURANCA = {
    # connect-src 'self' (MC39): o Dash ao vivo faz fetch SÓ da própria
    # origem (health//api/) — qualquer outro destino segue bloqueado
    "Content-Security-Policy": ("default-src 'none'; "
                                "style-src 'unsafe-inline'; "
                                "script-src 'unsafe-inline'; "
                                "connect-src 'self'; "
                                "img-src data:; base-uri 'none'; "
                                "form-action 'self'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _doc(titulo: str, corpo: str, refresh: int | None = None) -> str:
    """Documento HTML completo, autossuficiente (CSS/JS inline, nada externo).

    ``refresh``: opt-in de auto-recarga — vira <meta name="nomos-refresh">
    lida pelo JS próprio (cancelável/pausável); NÃO usamos http-equiv, que
    recarregaria no meio de uma decisão e apagaria o filtro digitado."""
    meta = (f'\n<meta name="nomos-refresh" content="{int(refresh)}">'
            if refresh else "")
    # boot do tema ANTES do <style>: aplica a escolha salva já na 1ª pintura
    # (sem flash). Sem escolha, o CSS respeita prefers-color-scheme sozinho.
    boot = ("<script>try{var t=localStorage.getItem('nomos-tema');"
            "if(t==='claro'||t==='escuro')"
            "document.documentElement.setAttribute('data-tema',t);}"
            "catch(e){}</script>")
    return ("<!doctype html><html lang=\"pt-br\"><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1\">" + meta + "\n" + boot + "\n<title>" +
            html.escape(titulo) + "</title>\n<style>" + _CSS + "</style>\n" +
            corpo + "\n<script>" + _JS + "</script>\n</html>")


# ---------------------------------------------------------------------------
# chat local — 2ª porta de escrita (MC38). LOCAL por lei: nuvem só via
# terminal com opt-in; sem motor pronto = fail-closed (nunca finge).
# ---------------------------------------------------------------------------
def responder_local(ctx, messages):
    """Roda SÓ o motor local (o mesmo caminho de `nomos chat`, sem nuvem).

    Devolve o texto da resposta, ou None se nenhum motor local estiver pronto
    — o painel então grava uma nota honesta, jamais uma resposta inventada.
    """
    import os

    from nomos.cognition.embutido import EmbeddedProvider
    from nomos.cognition.providers import OllamaProvider, OpenAICompatProvider
    from nomos.cognition.router import Router

    home = ctx["home"]
    try:
        ollama = OllamaProvider(
            host=os.environ.get("NOMOS_OLLAMA_HOST", "http://127.0.0.1:11434"),
            model=os.environ.get("NOMOS_OLLAMA_MODEL", "llama3.2"))
    except ValueError:
        ollama = None   # host não-loopback no ambiente: ignora (cadeado)
    try:
        oc = OpenAICompatProvider(
            base=os.environ.get("NOMOS_OPENAI_COMPAT_BASE",
                                "http://127.0.0.1:1234/v1"))
    except ValueError:
        oc = None
    router = Router(
        policy=ctx.get("policy"), gate=lambda *a, **k: False,
        approver=lambda *a, **k: False, audit=ctx["audit"], vault=None,
        ollama=ollama, embutido=EmbeddedProvider(home), openai_compat=oc)
    try:
        outcome = router._try_local(messages)   # None = nenhum motor local
    except Exception:
        return None
    return outcome.text if (outcome and outcome.ok) else None


def _contexto_chat(store, conversa_id: int, texto_usuario: str) -> list[dict]:
    """Monta as mensagens (system + histórico curto + fala nova)."""
    import contextlib
    msgs = [{"role": "system",
             "content": "Você é o agente pessoal do usuário no NOMOS. "
                        "Responda em português, direto."}]
    with contextlib.suppress(Exception):
        # turnos_para_contexto já devolve {role, content} de user/assistant
        msgs.extend(store.turnos_para_contexto(conversa_id, n=6))
    msgs.append({"role": "user", "content": texto_usuario})
    return msgs


# ---------------------------------------------------------------------------
# coleta de dados — SÓ leitura; nada aqui muda estado
# ---------------------------------------------------------------------------
def dados_dashboard(ctx) -> dict:
    """Coleta tudo que o painel mostra. Só leitura; nada muda de estado."""
    from nomos import __version__
    from nomos.cognition import engine_catalog as cat_mod
    from nomos.ext import skill_status as st
    from nomos.kernel import localidade
    from nomos.simple import doutor as doutor_mod
    from nomos.simple import rotinas as rot

    home = Path(ctx["home"])
    itens = doutor_mod.diagnostico_v011(home, ctx)
    cat = cat_mod.construir(home)
    modalidades = {m: [x.id for x in cat.prontos(m)]
                   for m in cat_mod.MODALIDADES_V011}
    eventos = []
    trilha = home / "logs" / "audit.jsonl"
    if trilha.exists():
        for linha in trilha.read_text(encoding="utf-8",
                                      errors="ignore").splitlines()[-12:]:
            try:
                reg = json.loads(linha)
                eventos.append({"ts": reg.get("ts"), "evento": reg.get("event")})
            except Exception:
                continue
    # Evidências de missões (MC29): pacotes auditáveis em ~/.nomos/evidencias
    evidencias = []
    dir_ev = home / "evidencias"
    if dir_ev.exists():
        from nomos.kernel import evidencia as ev_mod
        for pac in sorted(dir_ev.glob("EVIDENCIA_*"))[-8:]:
            integro, _ = ev_mod.verificar_pacote(pac)
            evidencias.append({"nome": pac.name, "integro": integro})

    # Motores: catálogo completo com custo/privacidade/prontidão (MC30)
    motores_tab = [{
        "id": m.id, "rotulo": m.rotulo, "local": bool(m.local),
        "custo": m.custo, "qualidade": m.qualidade, "pronto": bool(m.pronto),
    } for m in cat.motores]

    # Auditoria: verificação REAL da cadeia de hash (não só os últimos eventos)
    # verify() retorna (íntegro, índice_da_violação|-1) — a CONTAGEM vem de estado()
    try:
        cadeia_ok, _viol = ctx["audit"].verify()
        cadeia_n = ctx["audit"].estado()[0]
    except Exception:
        cadeia_ok, cadeia_n = False, 0

    # Capacidades (MC30-A4): o catálogo completo, com risco visível
    from nomos.ext import skill_catalogo as scat
    try:
        capacidades = scat.capacidades(home, home / "skills")
    except Exception:
        capacidades = []   # catálogo nunca derruba o painel

    # Atividade (MC39/MC39.1 — Dash): eventos da trilha, SÓ timestamps —
    # numa passada única, duas séries REAIS: por hora (24h) e por dia (7d).
    atividade_24h = {"buckets": [0] * 24, "total": 0}
    atividade_7d = {"buckets": [0] * 7, "total": 0}
    try:
        if trilha.exists():
            agora_ts = time.time()
            for linha in trilha.read_text(encoding="utf-8",
                                          errors="ignore").splitlines()[-20000:]:
                try:
                    ts = float(json.loads(linha).get("ts") or 0)
                except Exception:
                    continue
                idade_h = (agora_ts - ts) / 3600.0
                if 0 <= idade_h < 24:
                    # bucket 23 = hora atual; 0 = 24h atrás (ordem de leitura)
                    atividade_24h["buckets"][23 - int(idade_h)] += 1
                    atividade_24h["total"] += 1
                if 0 <= idade_h < 24 * 7:
                    atividade_7d["buckets"][6 - int(idade_h / 24)] += 1
                    atividade_7d["total"] += 1
    except Exception:
        atividade_24h = {"buckets": [0] * 24, "total": 0}
        atividade_7d = {"buckets": [0] * 7, "total": 0}

    # Memória 2.0 (MC31/B5): fila de candidatas visível — aprovar é no terminal
    try:
        from nomos.cognition.memory import Memory
        _mem = Memory(home / "memory.db")
        memoria = {"total": _mem.count(), "candidatas": len(_mem.candidatas())}
    except Exception:
        memoria = {"total": 0, "candidatas": 0}

    # Conversas (MC33): histórico read-only — títulos/metadados, nunca o conteúdo
    conversas = []
    try:
        from nomos.conversations.store import ConversationStore
        from nomos.kernel.audit import redact_text
        _cs = ConversationStore(home / "conversas.db")
        try:
            for c in _cs.listar(limite=8):
                # título é metadado (1ªs palavras) — redigido contra padrões
                # de segredo; o CORPO das mensagens nunca é lido nem exibido
                conversas.append({"id": c.id,
                                  "titulo": redact_text(c.titulo or "(sem título)"),
                                  "motor": c.motor, "fixada": bool(c.fixada),
                                  "turnos": c.n_turnos})
        finally:
            _cs.close()   # exceção no meio do loop não vaza a conexão sqlite
    except Exception:
        conversas = []

    # Agentes (MC33): oficiais + próprios, com risco máximo e ferramentas
    agentes = []
    try:
        from nomos.agents.registry import AgentRegistry
        reg = AgentRegistry(home)   # UMA instância: reusa o parse dos manifests
        for a in reg.listar():
            agentes.append({"nome": a.nome, "risco_max": a.risco_max,
                            "ferramentas": list(a.ferramentas),
                            "ativo": reg.ativo(a.nome)})
    except Exception:
        agentes = []

    # MCP (MC33): o NOMOS como servidor (tools read-only) + servers confiáveis
    try:
        from nomos.interface import mcp_catalogo as _mcat
        from nomos.interface import mcp_server as _msrv
        mcp = {"server_tools": [{"nome": t["name"],
                                 "descricao": t["description"]}
                                for t in _msrv.TOOLS],
               "confiaveis": _mcat.listar(home)["confiaveis"],
               "revogadas": _mcat.listar(home)["revogadas"]}
    except Exception:
        mcp = {"server_tools": [], "confiaveis": [], "revogadas": 0}

    # Política viva (MC29): o painel mostra o contrato, não uma cópia dele
    from nomos.council import forbidden_flags as ff
    from nomos.council import local_harness as lh
    from nomos.kernel.policy import DEFAULT_RULES
    politica = {
        "regras": dict(DEFAULT_RULES),
        "execucao_real_council": bool(lh.REAL_LOCAL_ENGINE_EXECUTION_ENABLED),
        "flags_proibidas": len(ff.FORBIDDEN_FLAGS),
    }

    # Roteador AO VIVO (Painel 4.0): a decisão explicada, por modalidade —
    # a mesma fonte da página roteador/, resumida para o rail de status
    roteador_vivo = []
    try:
        from nomos.cognition import engine_router as er
        for mod in cat_mod.MODALIDADES_V011:
            try:
                rel = er.relatorio_decisao(er.Tarefa(tipo=mod, modalidade=mod),
                                           home=home)
                dec = rel["decisao"]
                roteador_vivo.append({"modalidade": mod,
                                      "motor": dec["selected_engine"],
                                      "motivo": dec["reason"]})
            except Exception:
                roteador_vivo.append({"modalidade": mod, "motor": None,
                                      "motivo": "indisponível"})
    except Exception:
        roteador_vivo = []

    # Aprovações (Painel 4.0 / MC39.1): SÓ metadados/contagens — o campo
    # token dos arquivos JAMAIS é lido para cá. Além das pendentes, o Dash
    # mostra o placar das últimas 24h: aprovadas · negadas · expiradas.
    aprovacoes = {"pendentes": 0, "aprovadas_24h": 0,
                  "negadas_24h": 0, "expiradas_24h": 0}
    with contextlib.suppress(Exception):   # zeros valem se algo falhar
        from nomos.kernel.approvals import ApprovalQueue
        _fila = ApprovalQueue(home / "approvals", audit=ctx.get("audit"))
        aprovacoes["pendentes"] = len(_fila.pending())
        corte = time.time() - 24 * 3600
        for _p in (home / "approvals").glob("*.json"):
            try:
                _reg = json.loads(_p.read_text())
                quando = float(_reg.get("decided_at") or
                               _reg.get("expires") or 0)
                if quando < corte:
                    continue
                _status = _reg.get("status")
                if _status == "aprovada":
                    aprovacoes["aprovadas_24h"] += 1
                elif _status == "negada":
                    aprovacoes["negadas_24h"] += 1
                elif _status == "expirada":
                    aprovacoes["expiradas_24h"] += 1
            except Exception:
                continue

    # Conexões (MC40 — Dash Hub): o que está LIGADO e o que dá para ligar.
    # Tudo estado real: trust store de MCPs, motores prontos, skills,
    # rotinas — e os conectores de exemplo que acompanham o NOMOS.
    conexoes = {"mcp_confiaveis": [], "conectores_disponiveis": [],
                "motores_prontos": 0, "skills": 0, "rotinas_ativas": 0}
    with contextlib.suppress(Exception):
        conexoes["mcp_confiaveis"] = [
            s.get("nome", "?") for s in mcp.get("confiaveis", [])]
        conexoes["motores_prontos"] = sum(
            len(v) for v in modalidades.values())
        conexoes["skills"] = len(st.status_todas(home, home / "skills"))
        conexoes["rotinas_ativas"] = sum(
            1 for r in rot.listar(home) if r.get("ativa", True))
        # MC45.1: uma fonte de verdade — o MESMO helper de `nomos mcp
        # exemplos`. "ligado" = confiança REAL (impressão), não só o nome;
        # manifesto torto é ignorado; sem examples/ (wheel), lista vazia.
        from nomos.interface import mcp_catalogo as _cat
        conexoes["conectores_disponiveis"] = [
            {"nome": c["nome"], "ligado": c["status"] == "confiavel",
             "manifesto": c["manifesto"]}
            for c in _cat.conectores_exemplo(home)]

    # Sistema (Painel 4.0): metadados locais da instalação — nada sensível
    try:
        from nomos.simple.onboarding import carregar_perfil
        _perfil = carregar_perfil(home) or {}
        nome_agente = str(_perfil.get("nome_agente") or
                          _perfil.get("agente") or "NOMOS")
    except Exception:
        nome_agente = "NOMOS"
    sistema = {
        "python": _plataforma.python_version(),
        "plataforma": f"{_plataforma.system()} {_plataforma.release()}",
        "arquitetura": _plataforma.machine(),
        "home": str(home),
        "nome_agente": nome_agente,
        "bancos": {
            "memoria.db": (home / "memory.db").exists(),
            "conversas.db": (home / "conversas.db").exists(),
            "policy.json": (home / "policy.json").exists(),
        },
    }

    return {
        "versao": __version__,
        "so_local": localidade.esta_ligado(home),
        "status_geral": doutor_mod.status_geral(itens),
        "proximo_passo": doutor_mod.proximo_passo(itens),
        "checkup": itens,
        "modalidades": modalidades,
        "skills": st.status_todas(home, home / "skills"),
        "rotinas": rot.listar(home),
        "eventos": list(reversed(eventos)),
        "evidencias": evidencias,
        "politica": politica,
        "capacidades": capacidades,
        "motores": motores_tab,
        "auditoria": {"cadeia_integra": cadeia_ok, "eventos_total": cadeia_n},
        "memoria": memoria,
        "conversas": conversas,
        "agentes": agentes,
        "mcp": mcp,
        "roteador_vivo": roteador_vivo,
        "aprovacoes": aprovacoes,
        "sistema": sistema,
        "atividade_24h": atividade_24h,
        "atividade_7d": atividade_7d,
        "conexoes": conexoes,
    }


# ---------------------------------------------------------------------------
# blocos do layout — MC37: 5 ABAS (uma por vez), sem rail. Menos densidade,
# mesma informação. Cada aba agrupa seções afins; deep-links (#motores…)
# continuam válidos (o JS ativa a aba que contém a âncora).
# ---------------------------------------------------------------------------
# (data-aba, ícone, rótulo) — a ordem é a ordem da sidebar
_ABAS_NAV: list[tuple[str, str, str]] = [
    ("visao", "◉", "visão geral"),
    ("chat", "❯", "chat"),
    ("cerebro", "⚙", "cérebro"),
    ("capacidades", "❖", "capacidades"),
    ("operacao", "≡", "operação"),
    ("ajuda", "?", "ajuda"),
]


def _sidebar(d: dict, n_aprov: int) -> str:
    e = html.escape
    memo = d.get("memoria", {})
    badges = {
        "visao": (f'<span class="badge alerta">{n_aprov}</span>'
                  if n_aprov else ""),
        "cerebro": (f'<span class="badge">{memo.get("candidatas", 0)}</span>'
                    if memo.get("candidatas") else ""),
    }
    itens = []
    for aba, ico, rotulo in _ABAS_NAV:
        extra = badges.get(aba, "")
        itens.append(f'<a href="#{aba}" data-aba="{aba}">'
                     f'<span class="ico" aria-hidden="true">{ico}</span>'
                     f"{e(rotulo)}{extra}</a>")
    classe = {"PRONTO": "ok", "PARCIAL": "warn",
              "BLOQUEADO": "err"}[d["status_geral"]]
    sysbox = (
        '<div class="sysbox">'
        f'<div class="linha">status <span class="chip {classe}">'
        f'{e(d["status_geral"])}</span></div>'
        f'<div class="linha">{e(d["sistema"]["nome_agente"])}'
        f' · v{e(d["versao"])}</div>'
        f'<div class="linha">'
        f'{"🔒 só-local" if d["so_local"] else "🔌 nuvem plugada"}</div>'
        "</div>")
    # NOMOS Dash (MC39): a ferramenta própria de mission control, ao vivo
    dash = ('<a href="dash/" class="dashlink">'
            '<span class="ico" aria-hidden="true">◪</span>dash ao vivo '
            '<span aria-hidden="true">↗</span></a>')
    return ('<aside class="sidebar"><div class="brand">NOMOS'
            '<span class="cursor">▌</span></div>'
            '<p class="tagline">seu agente · sua máquina · suas regras</p>'
            '<nav class="menu" aria-label="seções do painel">'
            + "".join(itens) + dash + "</nav>" + sysbox + "</aside>")


def _bloco_atencao(d: dict, n_aprov: int) -> str:
    """O que espera VOCÊ — antes vivia no rail; agora abre a visão geral."""
    memo = d.get("memoria", {})
    itens = []
    if n_aprov:
        itens.append(f'<a href="#aprovacoes">{n_aprov} aprovação(ões) '
                     "esperando decisão</a>")
    if memo.get("candidatas"):
        itens.append(f'{memo["candidatas"]} memória(s) a revisar '
                     "(<code>nomos memoria revisar</code>)")
    if not d.get("auditoria", {}).get("cadeia_integra"):
        itens.append("cadeia de auditoria: verificar "
                     "(<code>nomos logs verify</code>)")
    ev_ruins = [x for x in d.get("evidencias", []) if not x.get("integro")]
    if ev_ruins:
        itens.append(f"{len(ev_ruins)} evidência(s) NÃO conferem")
    if not itens:
        return ('<div class="card ok">nada pendente ✓ <small>— quando algo '
                "precisar de você, aparece aqui</small></div>")
    linhas = "".join(f"<li>⚠ {x}</li>" for x in itens)
    return f'<div class="card warn"><b>Precisa de você</b><ul class="lista">{linhas}</ul></div>'


def _secao_chat(d: dict, chat: dict | None) -> str:
    """Aba chat (MC38) — estilo ChatGPT: histórico | thread + composer.

    ``chat=None`` ou desligado ⇒ SEM <form> (o painel puro segue read-only);
    o histórico (títulos redigidos) aparece de qualquer forma. Habilitado ⇒
    a 2ª porta de escrita governada: enviar roda motor LOCAL (fail-closed),
    conteúdo redigido na exibição, cada turno auditado.
    """
    e = html.escape
    corpo = ['<h2 id="chat">Chat local</h2>']
    hist = d.get("conversas", [])
    ligado = bool(chat and chat.get("habilitado") and chat.get("token"))

    if not ligado:
        corpo.append(
            '<div class="card">conversar aqui exige o painel local com a porta '
            "do chat ligada — rode <code>nomos painel</code> (motor local, "
            "fail-closed; <code>--sem-chat</code> desliga). Esta visão é "
            "somente leitura.</div>")
        corpo.append('<h3 id="conversas" class="mini-h">histórico</h3>')
        if not hist:
            corpo.append("<p>nenhuma conversa ainda. <code>nomos chat</code></p>")
        for c in hist:
            pino = "📌 " if c.get("fixada") else ""
            corpo.append(f'<div class="card filtravel">{pino}<b>#{c["id"]}</b> '
                         f'{e(c["titulo"])} <small>· {c.get("turnos", 0)} '
                         "turno(s)</small></div>")
        if hist:
            corpo.append("<p><small>só títulos e metadados aqui — o conteúdo "
                         "aparece quando você abre o chat local</small></p>")
        return "\n".join(corpo)

    base, token = chat["base"], chat["token"]
    aberta = chat.get("aberta")
    corpo.append('<div class="chat-wrap">')
    # coluna 1: histórico (a "barra lateral" do ChatGPT)
    corpo.append('<nav class="chat-hist" id="conversas" '
                 'aria-label="histórico de conversas">')
    corpo.append('<a class="nova" href="?conversa=nova#chat">+ nova conversa</a>')
    for c in hist:
        cls = "aberta" if (aberta and c["id"] == aberta.get("id")) else ""
        pino = "📌 " if c.get("fixada") else ""
        corpo.append(f'<a class="{cls}" href="?conversa={c["id"]}#chat">{pino}'
                     f'{e(c["titulo"])}<br><small>{c.get("turnos", 0)} '
                     "turno(s)</small></a>")
    if not hist:
        corpo.append('<div class="chat-vazio">sem conversas ainda</div>')
    corpo.append("</nav>")
    # coluna 2: thread + composer
    corpo.append('<div><div class="chat-thread">')
    msgs = chat.get("mensagens", [])
    if not aberta:
        corpo.append('<div class="chat-vazio">comece uma conversa nova abaixo '
                     "— ou escolha uma do histórico</div>")
    elif not msgs:
        corpo.append('<div class="chat-vazio">conversa vazia — mande a primeira '
                     "mensagem</div>")
    for m in msgs:
        role = m.get("role", "note")
        cls = role if role in ("user", "assistant") else "note"
        quem = {"user": "você", "assistant": "agente"}.get(role, "nota")
        corpo.append(f'<div class="bolha {cls}"><span class="quem">{quem}'
                     f'</span>{e(m.get("text", ""))}</div>')
    corpo.append("</div>")  # fim thread
    cid = aberta.get("id") if aberta else "nova"
    corpo.append(
        f'<form class="composer" method="post" action="{base}/chat/enviar">'
        f'<input type="hidden" name="token" value="{e(token)}">'
        f'<input type="hidden" name="conversa" value="{e(str(cid))}">'
        '<textarea name="mensagem" required rows="2" '
        'placeholder="escreva sua mensagem…" aria-label="mensagem"></textarea>'
        '<button type="submit">enviar</button></form>')
    corpo.append('<p class="chat-nota">roda só motor <b>local</b> (o cadeado '
                 "vale; nuvem só no terminal, com opt-in). Sem motor pronto, o "
                 "NOMOS avisa — nunca inventa. Cada turno fica na auditoria.</p>")
    corpo.append("</div></div>")  # fim coluna 2 + wrap
    return "\n".join(corpo)


def _bloco_ao_vivo(d: dict) -> str:
    """Motor escolhido por modalidade + atividade recente (metadados).

    MC37.1: a lista de modalidades sem motor pronto (ruído quando não há
    cérebro instalado) é recolhida num <details> — só os prontos ficam à
    vista, mantendo a honestidade ("sem motor pronto") sem inundar a tela.
    """
    e = html.escape
    rv = d.get("roteador_vivo") or []
    prontos = [r for r in rv if r.get("motor")]
    vazios = [r for r in rv if not r.get("motor")]
    partes = ['<div class="colunas2">', '<div><h3 class="mini-h">motor ao vivo</h3>']
    if not rv:
        partes.append('<div class="mini">roteador indisponível</div>')
    else:
        for r in prontos:
            partes.append(f'<div class="mini"><b>{e(r["modalidade"])}</b> → '
                          f'{e(r["motor"])}</div>')
        if vazios:
            nomes = ", ".join(e(r["modalidade"]) for r in vazios)
            resumo = (f"{len(vazios)} modalidade(s) sem motor pronto"
                      if prontos else
                      f"nenhum motor pronto ainda ({len(vazios)} modalidades)")
            partes.append(
                f'<details class="mais"><summary>{resumo}</summary>'
                f'<div class="mini">{nomes}<br><small>instale um cérebro: '
                "<code>nomos cerebro baixar</code></small></div></details>")
    partes.append('</div><div><h3 class="mini-h">atividade recente</h3>')
    for ev in d.get("eventos", [])[:5]:
        partes.append(f'<div class="mini"><code>{e(str(ev["evento"]))}</code> '
                      f'<small>{e(str(ev["ts"]))[:19]}</small></div>')
    if not d.get("eventos"):
        partes.append('<div class="mini">sem eventos ainda</div>')
    partes.append("</div></div>")
    return "".join(partes)


def _secao_aprovacoes(aprovacoes: list[dict] | None, n_meta: int) -> str:
    """A ÚNICA porta de ação do painel — e ela é o gate, não um atalho.

    Sem fila anexada (``aprovacoes=None``): seção informativa, sem <form>.
    Com fila: cada card carrega o token single-use da própria solicitação;
    decidir consome o token (reuso/expirada = recusa na fila, não aqui).
    """
    e = html.escape
    corpo = ['<h2 id="aprovacoes">Aprovações — você decide</h2>']
    if aprovacoes is None:
        rodape = (f"{n_meta} pendente(s) na fila — decida no terminal "
                  "(<code>nomos approvals list</code>)" if n_meta else
                  "nenhuma solicitação pendente")
        corpo.append(f'<div class="card">{rodape}<br><small>este modo do '
                     "painel é somente leitura; para decidir aqui, rode "
                     "<code>nomos painel</code> (fila anexada com token de "
                     "uso único, TTL 5 min)</small></div>")
        return "\n".join(corpo)
    if not aprovacoes:
        corpo.append('<div class="card ok">nenhuma solicitação pendente ✓'
                     "<br><small>quando o agente pedir licença (A1+), o "
                     "pedido aparece aqui com APROVAR/NEGAR — token de uso "
                     "único, expira sozinho em 5 min (fail-closed)</small>"
                     "</div>")
        return "\n".join(corpo)
    from nomos.kernel.policy import rotulo_categoria
    for a in aprovacoes:
        corpo.append(
            f'<div class="card aprov filtravel">'
            f'<b>{e(rotulo_categoria(a["category"]))}</b> '
            f'<span class="pill">expira em <span class="conta" '
            f'data-expira="{a["expira_epoch"]:.0f}">'
            f'{a["restante"]:.0f}s</span></span><br>'
            f'alvo: <span class="alvo">{e(a["target"])}</span><br>'
            f'motivo: {e(a["reason"])}<br>'
            f'<small>id {e(a["id"])}</small><br>'
            f'<form method="post" action="{a["base"]}/aprovacoes/decidir">'
            f'<input type="hidden" name="id" value="{e(a["id"])}">'
            f'<input type="hidden" name="token" value="{e(a["token"])}">'
            f'<input type="hidden" name="action" value="aprovar">'
            f'<button class="sim" type="submit">APROVAR</button></form>'
            f'<form method="post" action="{a["base"]}/aprovacoes/decidir">'
            f'<input type="hidden" name="id" value="{e(a["id"])}">'
            f'<input type="hidden" name="token" value="{e(a["token"])}">'
            f'<input type="hidden" name="action" value="negar">'
            f'<button class="nao" type="submit">NEGAR</button></form>'
            "</div>")
    corpo.append("<p><small>o token viaja UMA vez e morre no uso — reusar, "
                 "adivinhar ou atrasar não funciona (a fila decide, o painel "
                 "só transporta)</small></p>")
    return "\n".join(corpo)


# ---------------------------------------------------------------------------
# página principal
# ---------------------------------------------------------------------------
def render_html(d: dict, refresh: int | None = None,
                aprovacoes: list[dict] | None = None,
                chat: dict | None = None) -> str:
    """Página única (abas) com todas as seções — âncoras estáveis (MC33).

    ``aprovacoes=None`` ⇒ nenhum <form> de aprovação (read-only). ``chat=None``
    ou desligado ⇒ nenhum <form> de chat (a aba chat vira histórico read-only).
    """
    e = html.escape
    classe = {"PRONTO": "ok", "PARCIAL": "warn",
              "BLOQUEADO": "err"}[d["status_geral"]]
    n_aprov = (len(aprovacoes) if aprovacoes is not None
               else d.get("aprovacoes", {}).get("pendentes", 0))

    corpo: list[str] = []
    # --- topo fixo do conteúdo ---
    corpo.append(
        '<header class="topo"><h1>NOMOS <span class="lock">— painel local 🔒'
        "</span></h1>"
        '<p class="sub">ler é livre · agir passa pelo gate · só 127.0.0.1 · '
        "recarregue para atualizar</p>"
        '<div class="acoes"><input id="filtro" type="search" '
        'placeholder="filtrar seções e tabelas…" aria-label="filtrar"> '
        '<span id="filtro-n" aria-live="polite"></span> '
        '<button id="tema-btn" type="button" aria-pressed="false" '
        'title="alternar tema claro/escuro">◐ tema</button> '
        + ('<a class="ativo" href="./">auto: ligado — parar</a> '
           f'<span id="auto-estado">auto: {int(refresh)}s</span> '
           if refresh else
           '<a href="?refresh=30">auto-recarregar 30s</a> ')
        + '<a href="api/">api/ ↗</a> '
        '<a href="audit/">audit/ ↗</a> <a href="roteador/">roteador/ ↗</a> '
        '<a href="health/">health/ ↗</a></div></header>')

    # --- KPIs (5, enxutos: o essencial de relance) ---
    memo = d.get("memoria", {})
    aud = d.get("auditoria", {})
    n_prontos = sum(len(v) for v in d["modalidades"].values())
    cadeia_kpi = "íntegra" if aud.get("cadeia_integra") else "verificar"
    kpis = [
        (e(d["status_geral"]), "status geral"),
        ("🔒 local" if d["so_local"] else "🔌 nuvem", "cadeado"),
        (str(n_aprov), "aprovações"),
        (str(n_prontos), "motores prontos"),
        (cadeia_kpi, "cadeia auditoria"),
    ]
    corpo.append('<div class="kpis">' + "".join(
        f'<div class="kpi"><b>{v}</b><span>{lbl}</span></div>'
        for v, lbl in kpis) + "</div>")

    def _subnav(pares: list[tuple[str, str]]) -> str:
        return ('<nav class="subnav" aria-label="saltar na aba">'
                + " ".join(f'<a href="#{i}">{e(r)}</a>' for i, r in pares)
                + "</nav>")

    # =========================== ABA: visão geral ===========================
    aba_visao = [_subnav([("status", "status"), ("aprovacoes", "aprovações"),
                          ("checkup", "check-up")])]
    aba_visao.append(_bloco_atencao(d, n_aprov))
    aba_visao.append(
        f'<h2 id="status">Visão geral</h2>'
        f'<div class="card {classe}"><b>STATUS GERAL: {e(d["status_geral"])}'
        f"</b> · NOMOS {e(d['versao'])} · "
        f'{"modo só-local LIGADO 🔒" if d["so_local"] else "motores externos plugados 🔌"}'
        f"<br>próximo passo: <code>{e(d['proximo_passo'])}</code></div>")
    aba_visao.append(_bloco_ao_vivo(d))
    aba_visao.append(_secao_aprovacoes(aprovacoes, n_aprov))
    aba_visao.append('<h2 id="checkup">Check-up</h2>')
    for it in d["checkup"]:
        marca = "✅" if it["ok"] else ("❌" if it.get("bloqueante") else "⚠️")
        det = f' <small>{e(it["detalhe"])}</small>' if it.get("detalhe") else ""
        aba_visao.append(f'<div class="card filtravel">{marca} '
                         f'{e(it["titulo"])}{det}</div>')

    # ============================= ABA: cérebro =============================
    # (conversas migraram para a aba CHAT no MC38)
    aba_cerebro = [_subnav([("motores", "motores"), ("memoria", "memória")])]
    aba_cerebro.append('<h2 id="motores">Motores prontos por modalidade</h2>'
                       "<table><tr><th scope='col'>modalidade</th>"
                       "<th scope='col'>motores</th></tr>")
    for mod, ms in d["modalidades"].items():
        aba_cerebro.append(f'<tr class="filtravel"><td>{e(mod)}</td>'
                           f"<td>{e(', '.join(ms)) if ms else '—'}</td></tr>")
    aba_cerebro.append("</table>")
    aba_cerebro.append('<details class="mais"><summary>catálogo completo de '
                       "motores</summary><table>"
                       "<tr><th scope='col'>motor</th><th scope='col'>onde</th>"
                       "<th scope='col'>custo</th><th scope='col'>qualidade</th>"
                       "<th scope='col'>pronto</th></tr>")
    for m in d.get("motores", []):
        aba_cerebro.append(
            f'<tr class="filtravel"><td>{e(m["rotulo"])}</td>'
            f"<td>{'🔒 local' if m['local'] else '☁ nuvem (opt-in)'}</td>"
            f"<td>{e(m['custo'])}</td><td>{e(m['qualidade'])}</td>"
            f"<td>{'✓' if m['pronto'] else '—'}</td></tr>")
    aba_cerebro.append("</table></details>")
    aba_cerebro.append('<p><small>decisão explicada por modalidade: '
                       '<a href="roteador/">roteador/ ↗</a> · '
                       'conversas na aba <a href="#chat">chat</a></small></p>')
    pend = memo.get("candidatas", 0)
    aviso = (f'⚠️ <b>{pend}</b> candidata(s) aguardando SUA revisão — '
             f"<code>nomos memoria revisar</code>" if pend
             else "fila de candidatas vazia ✓")
    aba_cerebro.append(f'<h2 id="memoria">Memória local</h2><div class="card">'
                       f'{memo.get("total", 0)} memórias guardadas · {aviso}'
                       f"<br><small>aprovar/descartar é sempre decisão sua, "
                       f"no terminal — o painel só mostra</small></div>")

    # =============================== ABA: chat ==============================
    aba_chat = [_subnav([("chat", "conversa"), ("conversas", "histórico")]),
                _secao_chat(d, chat)]

    # ============================ ABA: capacidades ==========================
    aba_capac = [_subnav([("skills", "skills"), ("agentes", "agentes"),
                          ("capacidades", "catálogo"), ("mcp", "mcp")])]
    aba_capac.append('<h2 id="skills">Skills</h2>')
    if not d["skills"]:
        aba_capac.append("<p>nenhuma instalada. <code>nomos skills</code></p>")
    for s in d["skills"]:
        aba_capac.append(f'<div class="card filtravel">{e(s["name"])}@'
                         f'{e(s["version"])} — {e(s["estado"])} · '
                         f'risco {e(s["risco"])}</div>')
    aba_capac.append('<h2 id="agentes">Agentes</h2>')
    if not d.get("agentes"):
        aba_capac.append("<p>nenhum agente. <code>nomos agentes</code></p>")
    for a in d.get("agentes", []):
        estado = "ativo ✓" if a.get("ativo") else "inativo"
        ferr = ", ".join(a.get("ferramentas", [])) or "—"
        aba_capac.append(f'<div class="card filtravel">{e(a["nome"])} '
                         f'<span class="pill">risco máx {e(a["risco_max"])}</span>'
                         f'<span class="pill">{estado}</span><br>'
                         f"<small>ferramentas: {e(ferr)}</small></div>")
    aba_capac.append('<h2 id="capacidades">Capacidades (catálogo)</h2>')
    if not d.get("capacidades"):
        aba_capac.append("<p>catálogo vazio. <code>nomos skills catalogo</code></p>")
    for c in d.get("capacidades", []):
        aba_capac.append(
            f'<div class="card filtravel">{e(c["nome"])} '
            f'<small>[{e(c["status"])} · risco {e(c["risco"])}]</small><br>'
            f'{e(c["descricao"])}<br>'
            f'<small>entrada: {e(c["entrada"])} → {e(c["saida"])}</small></div>')
    mcp = d.get("mcp", {})
    aba_capac.append('<h2 id="mcp">MCP — Model Context Protocol</h2>')
    aba_capac.append(f'<div class="card ok"><b>NOMOS como servidor</b> '
                     f'({len(mcp.get("server_tools", []))} tools somente leitura) '
                     f"— <code>nomos mcp servir</code><br><small>"
                     + " · ".join(e(t["nome"]) for t in mcp.get("server_tools", []))
                     + "</small></div>")
    conf = mcp.get("confiaveis", [])
    if conf:
        aba_capac.append('<div class="card"><b>Servers confiáveis</b> '
                         f"({len(conf)} · {mcp.get('revogadas', 0)} revogado(s)):<br>"
                         + "<br>".join(f'<small>✓ {e(s["nome"])} '
                                       f'[{e(s.get("impressao", ""))}]</small>'
                                       for s in conf) + "</div>")
    else:
        aba_capac.append("<p>nenhum server MCP confiável. "
                         "<code>nomos mcp confiar &lt;manifesto&gt;</code></p>")

    # ============================= ABA: operação ============================
    aba_op = [_subnav([("rotinas", "rotinas"), ("evidencias", "evidências"),
                       ("politica", "política"), ("auditoria", "auditoria"),
                       ("sistema", "sistema")])]
    aba_op.append('<h2 id="rotinas">Rotinas</h2>')
    if not d["rotinas"]:
        aba_op.append("<p>nenhuma rotina. <code>nomos rotinas</code></p>")
    for r in d["rotinas"]:
        marca = "✓" if r.get("ativa", True) else "·"
        aba_op.append(f'<div class="card filtravel">[{marca}] {e(r["hora"])} — '
                      f'{e(r["nome"])} <small>({e(r["acao"])})</small></div>')
    aba_op.append('<h2 id="evidencias">Evidências de missões</h2>')
    if not d.get("evidencias"):
        aba_op.append("<p>nenhum pacote ainda. "
                      '<code>nomos evidencia criar "título"</code></p>')
    for ev_i in d.get("evidencias", []):
        marca = "✅ íntegro" if ev_i["integro"] else "❌ NÃO confere"
        aba_op.append(f'<div class="card filtravel">{e(ev_i["nome"])} — {marca}'
                      f' · <a href="ev/{e(ev_i["nome"])}/">abrir relatório</a>'
                      "</div>")
    pol = d.get("politica", {})
    if pol:
        aba_op.append('<h2 id="politica">Política de permissões (A0–A6)</h2>'
                      "<details class=\"mais\"><summary>ver a tabela A0–A6 "
                      "completa</summary><table>"
                      "<tr><th scope='col'>categoria</th>"
                      "<th scope='col'>default</th></tr>")
        for cat_nome, efeito in pol["regras"].items():
            aba_op.append(f'<tr class="filtravel"><td><code>{e(cat_nome)}'
                          f"</code></td><td>{e(efeito)}</td></tr>")
        aba_op.append("</table></details>")
        conselho = ("DESLIGADA (dry-run apenas)"
                    if not pol["execucao_real_council"] else "LIGADA")
        aba_op.append(f'<div class="card ok">Conselho: execução real de motor '
                      f'<b>{e(conselho)}</b> · {pol["flags_proibidas"]} flags '
                      f"proibidas fail-closed · aprovação humana obrigatória "
                      f"para ações sensíveis</div>")
    cadeia = ("íntegra ✅" if aud.get("cadeia_integra")
              else "⚠️ verificar (nomos logs verify)")
    aba_op.append(f'<h2 id="auditoria">Últimos eventos da auditoria</h2>'
                  f"<p><small>cadeia de hash: {cadeia} · "
                  f"{aud.get('eventos_total', 0)} eventos no total · "
                  f'<a href="audit/">trilha completa com busca ↗</a></small></p>'
                  '<details class="mais"><summary>ver os últimos eventos'
                  "</summary><table><tr><th scope='col'>quando (ts)</th>"
                  "<th scope='col'>evento</th></tr>")
    for ev in d["eventos"]:
        aba_op.append(f'<tr class="filtravel"><td>{e(str(ev["ts"]))}</td>'
                      f'<td><code>{e(str(ev["evento"]))}</code></td></tr>')
    aba_op.append("</table></details>")
    sis = d.get("sistema", {})
    if sis:
        bancos = " · ".join(f"{n} {'✓' if ok else '—'}"
                            for n, ok in sis.get("bancos", {}).items())
        aba_op.append(
            '<h2 id="sistema">Sistema</h2><table>'
            f'<tr class="filtravel"><td>agente</td><td><b>'
            f'{e(sis.get("nome_agente", "NOMOS"))}</b></td></tr>'
            f'<tr class="filtravel"><td>versão</td>'
            f'<td>NOMOS {e(d["versao"])}</td></tr>'
            f'<tr class="filtravel"><td>python</td>'
            f'<td>{e(sis.get("python", "?"))}</td></tr>'
            f'<tr class="filtravel"><td>plataforma</td>'
            f'<td>{e(sis.get("plataforma", "?"))} '
            f'({e(sis.get("arquitetura", "?"))})</td></tr>'
            f'<tr class="filtravel"><td>home</td>'
            f'<td><code>{e(sis.get("home", "~/.nomos"))}</code></td></tr>'
            f'<tr class="filtravel"><td>bancos locais</td><td>{bancos}</td></tr>'
            "</table>")

    # ============================== ABA: ajuda ==============================
    aba_ajuda = [
        '<h2 id="ajuda">Ajuda rápida</h2><table>'
        "<tr><th scope='col'>comando</th><th scope='col'>o que faz</th></tr>"
        '<tr class="filtravel"><td><code>nomos</code></td>'
        "<td>menu principal amigável</td></tr>"
        '<tr class="filtravel"><td><code>nomos doutor</code></td>'
        "<td>check-up + próximo passo recomendado</td></tr>"
        '<tr class="filtravel"><td><code>nomos chat</code></td>'
        "<td>conversar com o agente (local primeiro)</td></tr>"
        '<tr class="filtravel"><td><code>nomos cerebro baixar</code></td>'
        "<td>baixa o cérebro leve embutido (uma vez)</td></tr>"
        '<tr class="filtravel"><td><code>nomos skills</code></td>'
        "<td>instalar e governar habilidades</td></tr>"
        '<tr class="filtravel"><td><code>nomos approvals list</code></td>'
        "<td>fila de aprovações no terminal</td></tr>"
        '<tr class="filtravel"><td><code>nomos logs verify</code></td>'
        "<td>verifica a cadeia de hash da auditoria</td></tr>"
        "</table>"
        '<div class="card"><b>as leis da casa</b><br><small>'
        "1 · local por lei — nada sai da máquina sem opt-in explícito<br>"
        "2 · pede licença — ação sensível exige SUA aprovação (A0–A6)<br>"
        "3 · nunca finge — sem motor pronto, avisa; jamais inventa<br>"
        "4 · tudo deixa trilha — auditoria com cadeia de hash verificável"
        "</small></div>"
        '<p><small>dados técnicos (abrem outra página): '
        '<a href="api/">api/ ↗</a> · <a href="audit/">audit/ ↗</a> · '
        '<a href="roteador/">roteador/ ↗</a> · '
        '<a href="health/">health/ ↗</a></small></p>']

    def _aba(nome: str, ativa: bool, partes: list[str]) -> str:
        cls = "aba ativa" if ativa else "aba"
        return (f'<section class="{cls}" data-aba="{nome}" '
                f'aria-label="{nome}">' + "\n".join(partes) + "</section>")

    corpo.append(_aba("visao", True, aba_visao))
    corpo.append(_aba("chat", False, aba_chat))
    corpo.append(_aba("cerebro", False, aba_cerebro))
    corpo.append(_aba("capacidades", False, aba_capac))
    corpo.append(_aba("operacao", False, aba_op))
    corpo.append(_aba("ajuda", False, aba_ajuda))

    corpo.append("<footer>NOMOS · local por lei · o painel nunca executa nada "
                 "sozinho — toda ação exige SUA decisão com token de uso "
                 "único, e a trilha fica na auditoria.</footer>")

    conteudo = ('<a class="skip" href="#conteudo">pular para o conteúdo</a>'
                '<div class="app">' + _sidebar(d, n_aprov)
                + '<main id="conteudo" class="main">' + "\n".join(corpo)
                + "</main></div>")
    return _doc("NOMOS — painel local", conteudo, refresh)


# ---------------------------------------------------------------------------
# subpáginas (documentos próprios, mesmo visual, link de volta)
# ---------------------------------------------------------------------------
def _subpagina(titulo: str, corpo: str, base: str) -> str:
    shell = ('<div class="app"><main class="main" style="grid-column:1/-1;'
             'max-width:960px;margin:0 auto">'
             '<header class="topo"><h1>NOMOS <span class="lock">— '
             + html.escape(titulo) + '</span></h1><p class="sub"><a href="'
             + html.escape(base) + '/">← voltar ao painel</a></p></header>'
             + corpo +
             "<footer>NOMOS · local por lei · somente leitura nesta página."
             "</footer></main></div>")
    return _doc(f"NOMOS — {titulo}", shell)


# ---------------------------------------------------------------------------
# NOMOS Dash (MC39) — a ferramenta própria de dashboard: mission control
# ao vivo, numa tela. Princípios aplicados (pesquisa de referências):
# glanceability (a história em <1 min; máx. 8 métricas), tempo-real sem
# ansiedade (realce suave SÓ quando o valor muda; pausa com aba oculta),
# sparkline com histórico REAL (estilo btop), honestidade em falha
# ("reconectando…" — nunca inventa dado). Zero assets externos; fetch SÓ
# same-origin (CSP connect-src 'self'); leitura pura — dash não tem POST.
# ---------------------------------------------------------------------------
_CSS_DASH = """
 :root{--bg:#0A0F0D;--surface:#111814;--surface2:#0d1411;--line:#1d2a22;
   --neon:#5AF78E;--dim:#2BD968;--txt:#E8FFE8;--fraco:#7c9a84;
   --ciano:#56E1E9;--amarelo:#F2C14E;--vermelho:#FF5C57;
   --glow:0 0 8px rgba(90,247,142,.45)}
 *{box-sizing:border-box}
 body{font-family:'JetBrains Mono','IBM Plex Mono','SF Mono',Menlo,Consolas,
   monospace;background:var(--bg);color:var(--txt);margin:0;font-size:14px;
   line-height:1.5;min-height:100vh;display:flex;flex-direction:column}
 a{color:var(--ciano)} :focus-visible{outline:2px solid var(--neon);
   outline-offset:2px}
 header{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;
   padding:.8rem 1.2rem;border-bottom:1px solid var(--line)}
 h1{font-size:1rem;margin:0;color:var(--neon);text-shadow:var(--glow);
   letter-spacing:.14em}
 h1 small{color:var(--fraco);letter-spacing:0;font-weight:400}
 .hspace{margin-left:auto;display:flex;gap:.9rem;align-items:center;
   color:var(--fraco);font-size:.74rem}
 button.pausa{font:inherit;font-size:.74rem;background:var(--surface);
   color:var(--txt);border:1px solid var(--line);border-radius:6px;
   padding:.25rem .7rem;cursor:pointer}
 button.pausa[aria-pressed="true"]{border-color:var(--amarelo);
   color:var(--amarelo)}
 main{flex:1;padding:1.1rem 1.2rem;display:grid;gap:.8rem;
   grid-template-columns:repeat(12,1fr);align-content:start}
 .w{background:var(--surface);border:1px solid var(--line);border-radius:10px;
   padding:.8rem .95rem;min-width:0}
 .w h2{margin:0 0 .45rem;font-size:.66rem;color:var(--fraco);font-weight:400;
   text-transform:uppercase;letter-spacing:.16em}
 .w .valor{font-size:1.7rem;color:var(--neon);text-shadow:var(--glow);
   font-weight:700;line-height:1.1}
 .w .valor.warn{color:var(--amarelo)} .w .valor.err{color:var(--vermelho)}
 .w small{color:var(--fraco);font-size:.72rem;display:block;margin-top:.2rem}
 .c3{grid-column:span 3} .c4{grid-column:span 4} .c6{grid-column:span 6}
 .c8{grid-column:span 8} .c12{grid-column:span 12}
 .c8{display:flex;flex-direction:column}
 .c8 svg.spark{flex:1;min-height:64px;height:auto}
 @media(max-width:980px){.c3{grid-column:span 6}.c4{grid-column:span 6}
   .c6,.c8{grid-column:span 12}}
 @media(max-width:560px){.c3,.c4{grid-column:span 12}}
 .lista{margin:.2rem 0 0;padding:0;list-style:none;font-size:.8rem}
 .lista li{padding:.18rem 0;border-bottom:1px dashed var(--line)}
 .lista li:last-child{border-bottom:0}
 .lista .mot{color:var(--neon)} .lista .mod{color:var(--fraco)}
 svg.spark{width:100%;height:64px;display:block}
 svg.spark rect{fill:var(--dim)} svg.spark rect.hoje{fill:var(--neon)}
 .lista.atalhos li{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
 .lista.atalhos code{background:#0c1410;color:var(--neon);padding:.06rem .4rem;
   border-radius:4px;border:1px solid var(--line);font-size:.74rem}
 .lista.atalhos small{flex-basis:100%;margin:0}
 button.copiar{font:inherit;font-size:.64rem;background:var(--surface2);
   color:var(--fraco);border:1px solid var(--line);border-radius:5px;
   padding:.02rem .45rem;cursor:pointer}
 button.copiar:hover{color:var(--neon);border-color:var(--dim)}
 .conx-ok{color:var(--neon)} .conx-off{color:var(--fraco)}
 .faixa{float:right;display:inline-flex;gap:.25rem}
 .faixa-bt{font:inherit;font-size:.66rem;background:var(--surface2);
   color:var(--fraco);border:1px solid var(--line);border-radius:5px;
   padding:.05rem .5rem;cursor:pointer;letter-spacing:.08em}
 .faixa-bt[aria-pressed="true"]{color:var(--neon);border-color:var(--dim)}
 .mudou{animation:pulso .6s ease-out}
 @keyframes pulso{0%{background:rgba(90,247,142,.18)}100%{background:none}}
 @media (prefers-reduced-motion:reduce){.mudou{animation:none}}
 #estado[data-erro="1"]{color:var(--amarelo)}
 footer{padding:.6rem 1.2rem;border-top:1px solid var(--line);
   color:var(--fraco);font-size:.72rem;display:flex;gap:1rem;flex-wrap:wrap}
"""

_JS_DASH = """
(function(){
 'use strict';
 var pausado=false, ultAt=0, antes={};
 var $=function(id){return document.getElementById(id);};
 function marca(el){ if(!el) return;
   el.classList.remove('mudou'); void el.offsetWidth; el.classList.add('mudou'); }
 function poe(id, v, cls){ var el=$(id); if(!el) return;
   var s=String(v);
   if(antes[id]!==undefined && antes[id]!==s) marca(el.closest('.w')||el);
   antes[id]=s; el.textContent=s; if(cls!==undefined) el.className='valor '+cls; }
 function chip(status){ return status==='PRONTO'?'':(status==='PARCIAL'?'warn':'err'); }
 function spark(buckets){
   var svg=$('spark'); if(!svg||!buckets||!buckets.length) return;
   var W=480,H=64,n=buckets.length,bw=W/n-2,max=Math.max.apply(null,buckets.concat([1]));
   var out='';
   for(var i=0;i<n;i++){ var h=Math.max(2,Math.round((buckets[i]/max)*(H-6)));
     out+='<rect x="'+(i*(W/n)+1).toFixed(1)+'" y="'+(H-h)+'" width="'+bw.toFixed(1)
         +'" height="'+h+'"'+(i===n-1?' class="hoje"':'')+'></rect>'; }
   svg.innerHTML=out; }
 function saude(d){
   poe('status', d.status_geral, chip(d.status_geral));
   poe('aprov', d.aprovacoes_pendentes, d.aprovacoes_pendentes?'warn':'');
   poe('motores', d.motores_prontos, d.motores_prontos?'':'warn');
   poe('passo', d.proximo_passo);
   poe('uptime', d.uptime_hum||'—');
   if(d.mem_pico_mb!==undefined){ var m=$('mem'); if(m) m.textContent=d.mem_pico_mb; }
   var ul=$('avisos'); if(ul){ ul.textContent='';
     (d.avisos&&d.avisos.length?d.avisos:['nada pendente ✓']).forEach(function(a){
       var li=document.createElement('li'); li.textContent=a; ul.appendChild(li); }); }
   var lock=$('modo'); if(lock) lock.textContent=d.so_local?'🔒 só-local':'🔌 nuvem plugada';
   ultAt=Date.now(); var es=$('estado');
   es.removeAttribute('data-erro'); es.textContent='ao vivo'; }
 var series={a24:null,a7:null}, faixa='24h';
 function pinta(){
   var s=(faixa==='24h')?series.a24:series.a7; if(!s) return;
   spark(s.buckets); poe('ev24', s.total);
   var r=$('ev-rotulo'); if(r) r.textContent=(faixa==='24h')?'últimas 24h':'últimos 7 dias';
   var svg=$('spark'); if(svg) svg.setAttribute('aria-label',
     (faixa==='24h')?'eventos por hora, últimas 24 horas':'eventos por dia, últimos 7 dias');
 }
 function dados(d){
   if(d.secao==='atividade_24h'){ series.a24=d.dados; if(faixa==='24h') pinta(); }
   if(d.secao==='atividade_7d'){ series.a7=d.dados; if(faixa==='7d') pinta(); }
   if(d.secao==='aprovacoes'){ var dc=$('decisoes'); if(dc)
     dc.textContent='24h: ✓'+(d.dados.aprovadas_24h||0)+' aprovadas · ✗'
       +(d.dados.negadas_24h||0)+' negadas · ⏱'+(d.dados.expiradas_24h||0)+' expiradas'; }
   if(d.secao==='roteador_vivo'){ var ul=$('rotas'); if(!ul) return;
     ul.textContent='';
     d.dados.forEach(function(r){ var li=document.createElement('li');
       var mod=document.createElement('span'); mod.className='mod';
       mod.textContent=r.modalidade+' → ';
       var mot=document.createElement('span'); mot.className='mot';
       mot.textContent=r.motor||'— nenhum pronto';
       li.appendChild(mod); li.appendChild(mot); ul.appendChild(li); }); }
   if(d.secao==='conexoes'){ var uc=$('conexoes'); if(uc){ uc.textContent='';
     var c=d.dados;
     function li(html_ok, txt, extra){ var el=document.createElement('li');
       var b=document.createElement('span');
       b.className=html_ok?'conx-ok':'conx-off';
       b.textContent=html_ok?'● ':'○ '; el.appendChild(b);
       el.appendChild(document.createTextNode(txt));
       if(extra){ var s=document.createElement('small');
         s.textContent=extra; el.appendChild(s); }
       uc.appendChild(el); }
     li(c.motores_prontos>0, c.motores_prontos+' motor(es) pronto(s)',
        c.motores_prontos?'':'ligue um: nomos cerebro baixar');
     li(c.skills>0, c.skills+' skill(s) instalada(s)',
        c.skills?'':'instale: nomos skills');
     li(c.rotinas_ativas>0, c.rotinas_ativas+' rotina(s) ativa(s)',
        c.rotinas_ativas?'':'automatize: nomos rotinas');
     (c.conectores_disponiveis||[]).forEach(function(k){
       li(k.ligado, 'conector '+k.nome+(k.ligado?' — confiado':''),
          k.ligado?'':'ligar: nomos mcp confiar '+k.manifesto); });
     (c.mcp_confiaveis||[]).forEach(function(n){
       var achou=(c.conectores_disponiveis||[]).some(function(k){
         return k.nome===n; });
       if(!achou) li(true, 'MCP '+n+' — confiado'); });
   }}
   if(d.secao==='memoria'){ poe('memrev', d.dados.candidatas,
     d.dados.candidatas?'warn':''); }
   if(d.secao==='auditoria'){ poe('cadeia',
     d.dados.cadeia_integra?'íntegra':'verificar',
     d.dados.cadeia_integra?'':'warn'); } }
 function falhou(){ var es=$('estado'); es.setAttribute('data-erro','1');
   es.textContent='reconectando…'; }
 function pega(url, fn){ fetch(url,{cache:'no-store'}).then(function(r){
     if(!r.ok) throw 0; return r.json(); }).then(fn).catch(falhou); }
 // a página vive em .../dash/ (canônico) — os endpoints ficam um nível acima
 function ciclo5(){ if(pausado||document.hidden) return; pega('../health/',saude); }
 function ciclo30(){ if(pausado||document.hidden) return;
   ['atividade_24h','atividade_7d','roteador_vivo','memoria','auditoria',
    'aprovacoes','conexoes'].forEach(function(s){
     pega('../api/?secao='+s, dados); }); }
 document.addEventListener('click', function(ev){
   var bt=ev.target.closest('button.copiar'); if(!bt) return;
   var cmd=bt.getAttribute('data-cmd')||'';
   function feito(){ var t=bt.textContent; bt.textContent='copiado ✓';
     setTimeout(function(){ bt.textContent=t; }, 1200); }
   if(navigator.clipboard&&navigator.clipboard.writeText){
     navigator.clipboard.writeText(cmd).then(feito).catch(function(){});
   } });
 ['bt24','bt7d'].forEach(function(id){ var bt=$(id); if(!bt) return;
   bt.addEventListener('click', function(){
     faixa=(id==='bt24')?'24h':'7d';
     $('bt24').setAttribute('aria-pressed', faixa==='24h'?'true':'false');
     $('bt7d').setAttribute('aria-pressed', faixa==='7d'?'true':'false');
     pinta(); }); });
 function relogio(){ var el=$('faz'); if(!el) return;
   el.textContent = ultAt? Math.round((Date.now()-ultAt)/1000)+'s' : '—'; }
 var bt=$('pausa');
 if(bt){ bt.addEventListener('click', function(){ pausado=!pausado;
   bt.setAttribute('aria-pressed', pausado?'true':'false');
   bt.textContent = pausado?'retomar':'pausar';
   if(!pausado){ ciclo5(); ciclo30(); } }); }
 document.addEventListener('visibilitychange', function(){
   if(!document.hidden && !pausado){ ciclo5(); ciclo30(); } });
 ciclo5(); ciclo30();
 setInterval(ciclo5, 5000); setInterval(ciclo30, 30000);
 setInterval(relogio, 1000);
})();
"""


def _mem_pico_mb() -> float:
    """Pico de memória (RSS) do processo do painel, em MB — stdlib puro.

    ru_maxrss vem em KB no Linux e em BYTES no macOS; normaliza os dois.
    """
    try:
        import resource
        import sys as _sys
        pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 * 1024 if _sys.platform == "darwin" else 1024
        return round(pico / divisor, 1)
    except Exception:
        return 0.0


def _uptime_humano(segundos: float) -> str:
    """3661s → '1h01m'; 90s → '1m30s'; 12s → '12s' — curto e legível."""
    s = max(0, int(segundos))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def render_dash(versao: str) -> str:
    """Shell ESTÁTICO do NOMOS Dash — nenhum dado interpolado no HTML;
    tudo chega por polling same-origin e entra via textContent (XSS-safe).
    """
    e = html.escape
    corpo = (
        "<header><h1>NOMOS DASH <small>— mission control local 🔒</small></h1>"
        '<div class="hspace">'
        '<span aria-live="polite"><span id="estado">carregando…</span> · '
        'atualizado há <span id="faz">—</span></span>'
        '<button class="pausa" id="pausa" aria-pressed="false">pausar</button>'
        '<a href="../">← painel</a></div></header>'
        "<main>"
        # linha 1 — o essencial num relance (glanceability)
        '<div class="w c3"><h2>status geral</h2>'
        '<div class="valor" id="status">—</div>'
        '<small>doutor: <span id="passo">—</span></small></div>'
        '<div class="w c3"><h2>aprovações à sua espera</h2>'
        '<div class="valor" id="aprov">—</div>'
        '<small><a href="../#aprovacoes">decidir no painel →</a></small>'
        '<small id="decisoes">24h: —</small></div>'
        '<div class="w c3"><h2>memórias a revisar</h2>'
        '<div class="valor" id="memrev">—</div>'
        "<small>aprovar é sempre decisão sua</small></div>"
        '<div class="w c3"><h2>cadeia de auditoria</h2>'
        '<div class="valor" id="cadeia">—</div>'
        "<small>verificação real, a cada ciclo</small></div>"
        # linha 2 — histórico real (sparkline 24h/7d) + motores
        '<div class="w c8"><h2>atividade — <span id="ev-rotulo">últimas 24h'
        "</span> (<span id=\"ev24\">—</span> eventos) "
        '<span class="faixa"><button class="faixa-bt" id="bt24" '
        'aria-pressed="true">24h</button><button class="faixa-bt" id="bt7d" '
        'aria-pressed="false">7d</button></span></h2>'
        '<svg id="spark" class="spark" viewBox="0 0 480 64" '
        'preserveAspectRatio="none" role="img" '
        'aria-label="eventos de auditoria ao longo do tempo"></svg>'
        "<small>metadados da trilha — conteúdo nunca aparece</small></div>"
        '<div class="w c4"><h2>motores prontos</h2>'
        '<div class="valor" id="motores">—</div>'
        '<ul class="lista" id="rotas"><li>carregando…</li></ul></div>'
        # linha 3 — avisos honestos
        '<div class="w c12"><h2>atenção</h2>'
        '<ul class="lista" id="avisos"><li>carregando…</li></ul></div>'
        # linha 4 — Dash Hub (MC40): ligar ferramentas + encurtar o dia a dia
        '<div class="w c6"><h2>conexões — ligue suas ferramentas</h2>'
        '<ul class="lista" id="conexoes"><li>carregando…</li></ul>'
        "<small>ligar passa pelo gate no terminal — o Dash mostra o "
        "caminho, você decide</small></div>"
        '<div class="w c6"><h2>atalhos do dia a dia</h2>'
        '<ul class="lista atalhos">'
        '<li><code>nomos missao planejar organizar ~/Downloads</code>'
        '<button class="copiar" data-cmd="nomos missao planejar organizar '
        '~/Downloads">copiar</button><small>arruma a bagunça com plano + '
        "desfazer</small></li>"
        '<li><code>nomos rotinas</code>'
        '<button class="copiar" data-cmd="nomos rotinas">copiar</button>'
        "<small>briefing e check-up automáticos, na sua hora</small></li>"
        '<li><code>nomos backup</code>'
        '<button class="copiar" data-cmd="nomos backup">copiar</button>'
        "<small>seu NOMOS inteiro num arquivo cifrado</small></li>"
        '<li><code>nomos mcp confiar examples/mcp/telegram/manifesto.json'
        "</code>"
        '<button class="copiar" data-cmd="nomos mcp confiar '
        'examples/mcp/telegram/manifesto.json">copiar</button>'
        "<small>liga o conector Telegram (Bot API oficial)</small></li>"
        '<li><code>nomos rotinas briefing --telegram SEU_CHAT_ID</code>'
        '<button class="copiar" data-cmd="nomos rotinas briefing '
        '--telegram SEU_CHAT_ID">copiar</button>'
        "<small>o briefing do dia no seu Telegram — com o seu OK (A3); "
        "agende com: nomos rotinas agendar --telegram SEU_CHAT_ID</small>"
        "</li>"
        "</ul></div>"
        "</main>"
        "<footer><span>NOMOS v" + e(versao) + "</span>"
        '<span id="modo">—</span>'
        '<span>uptime do painel: <span id="uptime">—</span></span>'
        '<span>pico de memória: <span id="mem">—</span> MB</span>'
        "<span>ao vivo: health/ 5s · seções 30s · pausa sozinho quando a "
        "aba se esconde</span>"
        "<span>local por lei — este dash só LÊ; agir continua no gate</span>"
        "</footer>")
    return ("<!doctype html><html lang=\"pt-br\"><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1\">\n<title>NOMOS Dash</title>\n<style>"
            + _CSS_DASH + "</style>\n" + corpo
            + "\n<script>" + _JS_DASH + "</script>\n</html>")


class DashboardServer:
    """Servidor do painel — loopback apenas; ação SÓ pela porta de aprovações.

    ``fila_aprovacoes``: por padrão o painel anexa a fila file-based de
    ``~/.nomos/approvals`` (a mesma do terminal). Passe ``False`` para um
    painel 100% somente leitura (nenhum POST aceito).
    """

    def __init__(self, ctx, host: str = "127.0.0.1", port: int = 0,
                 fila_aprovacoes=None, cache_s: float = 0.0,
                 chat_habilitado: bool = False):
        if host != "127.0.0.1":
            raise ValueError("painel é LOCAL por projeto: bind permitido só em 127.0.0.1")
        self.ctx = ctx
        self.secret = secrets.token_urlsafe(16)
        self.iniciado_em = time.time()   # uptime real p/ o Dash e o health
        # 2ª porta de escrita (MC38): o chat local. Nasce DESLIGADO — o painel
        # puro segue read-only; `nomos painel` liga. Token CSRF por servidor.
        self.chat_habilitado = bool(chat_habilitado)
        self.chat_token = secrets.token_urlsafe(32)
        # cache opcional da coleta (dados_dashboard refaz verify() + probes a
        # cada GET; com health/ em polling isso multiplica leituras). 0 =
        # desligado (padrão: cada GET reflete o estado na hora).
        self.cache_s = float(cache_s)
        self._cache: tuple[float, dict | None] = (0.0, None)
        self._cache_lock = threading.Lock()
        if fila_aprovacoes is False:
            self.fila = None
        elif fila_aprovacoes is not None:
            self.fila = fila_aprovacoes
        else:
            try:
                from nomos.kernel.approvals import ApprovalQueue
                self.fila = ApprovalQueue(Path(ctx["home"]) / "approvals",
                                          audit=ctx.get("audit"))
            except Exception:
                self.fila = None   # sem fila ⇒ painel vira somente leitura
        painel = self

        def _dados() -> dict:
            """Coleta com cache opcional (TTL curto) — ver cache_s acima."""
            if painel.cache_s <= 0:
                return dados_dashboard(painel.ctx)
            with painel._cache_lock:
                ts, dados = painel._cache
                agora = time.time()
                if dados is None or agora - ts > painel.cache_s:
                    dados = dados_dashboard(painel.ctx)
                    painel._cache = (agora, dados)
                return dados

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _responder(self, code, texto, tipo="text/html"):
                data = texto.encode()
                self.send_response(code)
                self.send_header("Content-Type", f"{tipo}; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in _HEADERS_SEGURANCA.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            # ---------------- GET ----------------
            def do_GET(self):
                caminho, _, query = self.path.partition("?")
                base = f"/d/{painel.secret}"
                if caminho == base:
                    # sem a barra final os links relativos (api/, audit/)
                    # resolveriam para /d/... — redireciona para a canônica
                    self.send_response(301)
                    destino = base + "/" + (f"?{query}" if query else "")
                    self.send_header("Location", destino)
                    for k, v in _HEADERS_SEGURANCA.items():
                        self.send_header(k, v)
                    self.end_headers()
                    return None
                caminho = caminho.rstrip("/")
                if caminho == base:
                    refresh = None
                    m = re.search(r"(?:^|&)refresh=(\d{1,4})(?:&|$)", query)
                    if m and 5 <= int(m.group(1)) <= 3600:
                        refresh = int(m.group(1))   # fora da faixa: ignorado
                    try:
                        corpo = render_html(_dados(),
                                            refresh=refresh,
                                            aprovacoes=self._aprovacoes(base),
                                            chat=self._chat(base, query))
                    except Exception as exc:   # painel nunca derruba nada
                        return self._responder(
                            500, f"painel indisponível: {type(exc).__name__}",
                            "text/plain")
                    return self._responder(200, corpo)
                if caminho == base + "/api":
                    return self._api(query)
                if caminho == base + "/health":
                    return self._health()
                if caminho == base + "/dash":
                    # NOMOS Dash (MC39): shell estático; dados via polling.
                    # Como a raiz: forma canônica com barra final, para os
                    # caminhos relativos (../health/, ../api/) resolverem.
                    if not self.path.partition("?")[0].endswith("/"):
                        self.send_response(301)
                        self.send_header("Location", base + "/dash/")
                        for k, v in _HEADERS_SEGURANCA.items():
                            self.send_header(k, v)
                        self.end_headers()
                        return None
                    from nomos import __version__ as _v
                    return self._responder(200, render_dash(_v))
                if caminho == base + "/audit":
                    return self._pagina_audit(query)
                if caminho == base + "/roteador":
                    return self._pagina_roteador()
                if caminho.startswith(base + "/ev/"):
                    return self._servir_evidencia(caminho[len(base) + 4:])
                return self._responder(404, "não encontrado", "text/plain")

            def _chat(self, base, query) -> dict | None:
                """Dados da aba chat: histórico + conversa aberta (conteúdo
                REDIGIDO). Sem chat habilitado ⇒ None (aba vira read-only)."""
                if not painel.chat_habilitado:
                    return None
                dados = {"habilitado": True, "token": painel.chat_token,
                         "base": base, "aberta": None, "mensagens": []}
                import contextlib
                sel = (parse_qs(query).get("conversa") or [""])[0]
                if sel and sel != "nova":
                    # id inválido/ilegível: trata como conversa nova (não quebra)
                    with contextlib.suppress(Exception):
                        from nomos.conversations.store import ConversationStore
                        from nomos.kernel.audit import redact_text
                        cid = int(sel)
                        cs = ConversationStore(Path(painel.ctx["home"]) /
                                               "conversas.db")
                        try:
                            conv, turnos = cs.abrir(cid)
                        finally:
                            cs.close()
                        if conv is not None:
                            dados["aberta"] = {"id": conv.id,
                                               "titulo": conv.titulo or ""}
                            dados["mensagens"] = [
                                {"role": t.role,
                                 "text": redact_text(t.text or "")}
                                for t in turnos]
                return dados

            def _aprovacoes(self, base) -> list | None:
                """Pendências da fila com token single-use — só para o HTML."""
                if painel.fila is None:
                    return None
                from nomos.kernel.approvals import ApprovalError
                itens: list[dict] = []
                try:
                    pendentes = painel.fila.pending()
                    agora = painel.fila.clock()
                except Exception:
                    return itens
                for a in pendentes:
                    try:
                        token = painel.fila.token_of(a.id)
                    except ApprovalError:
                        continue
                    itens.append({"id": a.id, "category": a.category,
                                  "target": a.target, "reason": a.reason,
                                  "restante": max(0.0, a.expires - agora),
                                  "expira_epoch": a.expires,
                                  "token": token, "base": base})
                return itens

            def _api(self, query: str):
                try:
                    dados = _dados()
                except Exception as exc:
                    return self._responder(
                        500, f"api indisponível: {type(exc).__name__}",
                        "text/plain")
                secao = (parse_qs(query).get("secao") or [None])[0]
                if secao is not None:
                    if secao not in dados:
                        corpo = json.dumps(
                            {"erro": "seção desconhecida",
                             "disponiveis": sorted(dados.keys())},
                            ensure_ascii=False)
                        return self._responder(404, corpo, "application/json")
                    corpo = json.dumps({"secao": secao, "dados": dados[secao]},
                                       ensure_ascii=False, indent=2,
                                       default=str)
                    return self._responder(200, corpo, "application/json")
                return self._responder(
                    200, json.dumps(dados, ensure_ascii=False, indent=2,
                                    default=str), "application/json")

            def _health(self):
                """Sinal de vida p/ scripts, rotinas e integrações.

                Além do "estou vivo", devolve SINAIS acionáveis: status
                geral do doutor, o próximo passo recomendado e a lista de
                avisos (o mesmo "atenção" do rail) — tudo metadado, nada
                sensível. `ok` = o painel responde; `saudavel` = nada
                bloqueado E nenhum aviso pendente.
                """
                try:
                    d = _dados()
                    n_pend = (len(painel.fila.pending())
                              if painel.fila is not None
                              else d.get("aprovacoes", {}).get("pendentes", 0))
                    avisos = []
                    if n_pend:
                        avisos.append(f"{n_pend} aprovação(ões) esperando "
                                      "sua decisão")
                    memo = d.get("memoria", {})
                    if memo.get("candidatas"):
                        avisos.append(f'{memo["candidatas"]} memória(s) '
                                      "aguardando revisão")
                    if not d.get("auditoria", {}).get("cadeia_integra"):
                        avisos.append("cadeia de auditoria: verificar")
                    ev_ruins = [x for x in d.get("evidencias", [])
                                if not x.get("integro")]
                    if ev_ruins:
                        avisos.append(f"{len(ev_ruins)} evidência(s) "
                                      "não conferem")
                    corpo = json.dumps({
                        "ok": True,
                        "saudavel": (d["status_geral"] != "BLOQUEADO"
                                     and not avisos),
                        "status_geral": d["status_geral"],
                        "proximo_passo": d["proximo_passo"],
                        "avisos": avisos,
                        "versao": d["versao"],
                        "so_local": d["so_local"],
                        "aprovacoes_pendentes": n_pend,
                        "motores_prontos": sum(
                            len(v) for v in d["modalidades"].values()),
                        "uptime_s": int(time.time() - painel.iniciado_em),
                        "uptime_hum": _uptime_humano(
                            time.time() - painel.iniciado_em),
                        "mem_pico_mb": _mem_pico_mb(),
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    }, ensure_ascii=False)
                    return self._responder(200, corpo, "application/json")
                except Exception as exc:
                    return self._responder(
                        500, json.dumps({"ok": False,
                                         "erro": type(exc).__name__}),
                        "application/json")

            def _pagina_audit(self, query: str = ""):
                """Auditoria completa: cadeia verificada + busca server-side."""
                e = html.escape
                base = f"/d/{painel.secret}"
                try:
                    ok, _viol = painel.ctx["audit"].verify()
                    total = painel.ctx["audit"].estado()[0]
                except Exception:
                    ok, total = False, 0
                q = (parse_qs(query).get("q") or [""])[0][:80]
                linhas = [f"<h2>Auditoria — cadeia de hash "
                          f"{'íntegra ✅' if ok else '⚠️ verificar'} · "
                          f"{total} eventos</h2>",
                          '<form method="get" class="acoes" '
                          'style="margin:.6rem 0">'
                          f'<input type="search" name="q" value="{e(q)}" '
                          'placeholder="buscar evento… (ex.: approval)" '
                          'aria-label="buscar na auditoria">'
                          '<button type="submit">buscar</button></form>']
                trilha = Path(painel.ctx["home"]) / "logs" / "audit.jsonl"
                mostrados = 0
                tabela = ["<table><tr><th scope='col'>quando (ts)</th><th scope='col'>evento</th></tr>"]
                if trilha.exists():
                    for linha in trilha.read_text(
                            encoding="utf-8",
                            errors="ignore").splitlines()[-500:][::-1]:
                        try:
                            reg = json.loads(linha)
                        except Exception:
                            continue
                        evento, ts = str(reg.get("event")), str(reg.get("ts"))
                        if q and q.lower() not in evento.lower() \
                                and q.lower() not in ts.lower():
                            continue
                        mostrados += 1
                        if mostrados > 100:
                            break
                        tabela.append(f"<tr><td>{e(ts)}</td>"
                                      f"<td><code>{e(evento)}</code></td></tr>")
                tabela.append("</table>")
                if q:
                    linhas.append(f"<p><small>filtro ativo: "
                                  f"<code>{e(q)}</code> · {mostrados} "
                                  f'resultado(s) · <a href="?">limpar</a>'
                                  "</small></p>")
                linhas += tabela
                linhas.append("<p><small>metadados apenas — conteúdo "
                              "nunca aparece; trilha completa em "
                              "<code>~/.nomos/logs/audit.jsonl</code></small></p>")
                self._responder(200, _subpagina("auditoria completa",
                                                "\n".join(linhas), base))

            def _pagina_roteador(self):
                """Decisões do roteador, explicadas, por modalidade — só leitura."""
                e = html.escape
                base = f"/d/{painel.secret}"
                try:
                    from nomos.cognition import engine_catalog as cat_mod
                    from nomos.cognition import engine_router as er
                    home = Path(painel.ctx["home"])
                    linhas = ["<h2>Roteador — decisão explicada por modalidade</h2>"]
                    for mod in cat_mod.MODALIDADES_V011:
                        rel = er.relatorio_decisao(
                            er.Tarefa(tipo=mod, modalidade=mod), home=home)
                        dec = rel["decisao"]
                        escolhido = dec["selected_engine"] or "— (nenhum pronto)"
                        linhas.append(
                            f'<div class="card"><b>{e(mod)}</b> → '
                            f"<code>{e(escolhido)}</code><br>"
                            f'<small>{e(dec["reason"])}</small><br>'
                            f"<small>regras: "
                            f'{e(" · ".join(rel["trace"]["regras_aplicadas"]))}'
                            "</small></div>")
                    linhas.append("<p><small>dados, não ação: executar continua "
                                  "passando pelo gate de aprovação</small></p>")
                except Exception as exc:
                    return self._responder(
                        500, f"roteador indisponível: {type(exc).__name__}",
                        "text/plain")
                self._responder(200, _subpagina("roteador", "\n".join(linhas),
                                                base))

            def _servir_evidencia(self, nome: str):
                """RELATORIO.md de um pacote — leitura, nome estrito, sem traversal."""
                if not re.fullmatch(r"EVIDENCIA_[A-Za-z0-9_-]+", nome):
                    return self._responder(404, "não encontrado", "text/plain")
                raiz = (Path(painel.ctx["home"]) / "evidencias").resolve()
                alvo = (raiz / nome / "RELATORIO.md").resolve()
                # cinto e suspensório: mesmo com o regex, o alvo TEM de estar na raiz
                if raiz not in alvo.parents or not alvo.is_file():
                    return self._responder(404, "não encontrado", "text/plain")
                self._responder(200, alvo.read_text(encoding="utf-8"),
                                "text/plain")

            # ---------------- POST ----------------
            def _corpo_post(self, base, limite=8192):
                """Lê e valida o corpo de um POST (comum às duas portas).
                Devolve (form, None) ou (None, (code, titulo, msg))."""
                try:
                    tam = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return None, (400, "pedido inválido", "Content-Length não numérico")
                if tam < 0:
                    return None, (400, "pedido inválido", "Content-Length negativo")
                if tam > limite:
                    return None, (413, "pedido grande demais",
                                  f"corpo acima de {limite} bytes não é desta porta")
                try:
                    return parse_qs(self.rfile.read(tam).decode()), None
                except UnicodeDecodeError:
                    return None, (400, "pedido inválido", "corpo não é UTF-8")

            def _post_chat(self, base):
                """2ª porta de escrita (MC38): envia uma mensagem ao motor
                LOCAL. Token CSRF por servidor; fail-closed sem motor."""
                def _erro(code, titulo, msg, ancora="#chat"):
                    corpo = (f"<p>{html.escape(msg)}</p><p><a href=\"{base}/"
                             f'{ancora}">← voltar ao painel</a></p>')
                    return self._responder(code, _subpagina(titulo, corpo, base))

                import hmac
                form, err = self._corpo_post(base)
                if err:
                    return _erro(*err)
                token = (form.get("token") or [""])[0]
                if not hmac.compare_digest(token, painel.chat_token):
                    return _erro(403, "recusado",
                                 "token do chat inválido (recarregue o painel)")
                msg = (form.get("mensagem") or [""])[0].strip()
                if not msg:
                    return _erro(400, "mensagem vazia", "escreva algo para enviar")
                if len(msg) > 6000:
                    return _erro(413, "mensagem longa demais",
                                 "reduza a mensagem (máx ~6000 caracteres)")
                sel = (form.get("conversa") or ["nova"])[0]
                from nomos.conversations.store import ConversationStore
                cs = ConversationStore(Path(painel.ctx["home"]) / "conversas.db")
                try:
                    try:
                        cid = int(sel)
                        conv, _ = cs.abrir(cid)
                        if conv is None:
                            cid = cs.nova_conversa(motor="painel")
                    except (ValueError, TypeError):
                        cid = cs.nova_conversa(motor="painel")
                    cs.add_turno(cid, "user", msg)
                    painel.ctx["audit"].append("chat.painel.enviou",
                                               conversa=cid, egress="nenhum")
                    contexto = _contexto_chat(cs, cid, msg)
                    resposta = responder_local(painel.ctx, contexto)
                    if resposta:
                        cs.add_turno(cid, "assistant", resposta)
                        painel.ctx["audit"].append("chat.painel.respondeu",
                                                    conversa=cid, egress="nenhum")
                    else:
                        # fail-closed: nunca finge. Grava nota honesta.
                        cs.add_turno(
                            cid, "note",
                            "sem motor local pronto — instale o cérebro "
                            "(nomos cerebro baixar) ou ligue o Ollama. "
                            "Nenhuma resposta foi inventada.")
                        painel.ctx["audit"].append("chat.painel.sem_motor",
                                                   conversa=cid)
                finally:
                    cs.close()
                # PRG: volta à conversa (evita reenvio no F5)
                self.send_response(303)
                self.send_header("Location", f"{base}/?conversa={cid}#chat")
                for k, v in _HEADERS_SEGURANCA.items():
                    self.send_header(k, v)
                self.end_headers()
                return None

            def do_POST(self):
                """Duas portas de escrita (MC38): aprovacoes/decidir (token
                single-use, TTL) e chat/enviar (token CSRF, motor local,
                fail-closed). Qualquer outra coisa = 405.
                """
                base = f"/d/{painel.secret}"
                rota = self.path.rstrip("/")

                # porta 2: chat local (só se habilitado)
                if rota == base + "/chat/enviar":
                    if not painel.chat_habilitado:
                        corpo = ('<p>o chat está desligado neste painel '
                                 "(<code>--sem-chat</code>).</p>"
                                 f'<p><a href="{base}/#chat">← voltar</a></p>')
                        return self._responder(
                            405, _subpagina("chat desligado", corpo, base))
                    return self._post_chat(base)

                def _erro(code: int, titulo: str, msg: str):
                    # beco sem saída, nunca: todo erro do fluxo de decisão
                    # devolve página mínima com caminho de volta ao painel
                    corpo = (f"<p>{html.escape(msg)}</p>"
                             f'<p><a href="{base}/#aprovacoes">'
                             "← voltar ao painel</a></p>")
                    return self._responder(code,
                                           _subpagina(titulo, corpo, base))

                # porta 1: aprovações
                if (painel.fila is None
                        or rota != base + "/aprovacoes/decidir"):
                    return _erro(405, "método não permitido",
                                 "escrever só existe nas portas de aprovações "
                                 "e chat local")
                from nomos.kernel.approvals import ApprovalError
                try:
                    tam = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return _erro(400, "pedido inválido",
                                 "Content-Length não numérico")
                if tam < 0:
                    return _erro(400, "pedido inválido",
                                 "Content-Length negativo")
                if tam > 8192:   # formulário minúsculo; nada além disso
                    return _erro(413, "pedido grande demais",
                                 "o formulário de decisão tem poucos bytes — "
                                 "corpo acima de 8 KiB não é dele")
                try:
                    form = parse_qs(self.rfile.read(tam).decode())
                except UnicodeDecodeError:
                    return _erro(400, "pedido inválido", "corpo não é UTF-8")
                rid = (form.get("id") or [""])[0]
                token = (form.get("token") or [""])[0]
                acao = (form.get("action") or [""])[0]
                if acao not in ("aprovar", "negar"):
                    return _erro(400, "ação inválida",
                                 "a ação precisa ser aprovar ou negar")
                try:
                    painel.fila.decide(rid, token, approve=(acao == "aprovar"))
                except ApprovalError as exc:
                    return _erro(409, "decisão recusada", f"recusado: {exc}")
                # PRG: decidir → recarregar o painel (evita repost no F5)
                self.send_response(303)
                self.send_header("Location", base + "/#aprovacoes")
                for k, v in _HEADERS_SEGURANCA.items():
                    self.send_header(k, v)
                self.end_headers()
                return None

        self._server = ThreadingHTTPServer((host, port), Handler)
        self.port = self._server.server_port
        self.url = f"http://127.0.0.1:{self.port}/d/{self.secret}/"
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
