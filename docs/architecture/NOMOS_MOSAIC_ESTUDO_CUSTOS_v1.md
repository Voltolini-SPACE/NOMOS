# NOMOS · MOSAIC — Estudo de Custos e Precificação (v1)

- **Data:** 2026-07-09 · **Câmbio usado:** USD→BRL = **5,16** (open.er-api, 09/07/2026)
- **Método:** pesquisa de preços reais (fontes primárias, citadas na §11) + modelo de unit economics em `mosaic_custos.py` (roda e recalcula).
- **Compromisso:** nada inventado. Preços unitários vêm de fontes de 2026; **premissas de USO são estimativas explícitas**, a validar em piloto. Nível de confiança marcado em cada bloco.

---

## 0. Resumo executivo

Hospedar o Mosaic é **viável em ticket baixo/médio** — desde que **cotas por plano + roteamento de modelo barato** estejam no produto desde o dia 1. Sem isso, os clientes pesados **dão prejuízo**.

Preços recomendados (mensal), com a margem bruta no caso esperado:

| Plano | Preço | Custo/cliente (esperado) | Margem bruta | Break-even |
|---|---|---|---|---|
| **Base (Essencial)** | **R$ 97** | ~R$ 22 | **~74%** | ~10 clientes |
| **Pro** | **R$ 347** | ~R$ 85 | **~72%** | ~3 clientes |
| **Business** | **R$ 797** | ~R$ 267 | **~62%** | ~1,4 cliente |

Em dólar, os tickets são ~US$ 19 / 67 / 154 — baixo/médio, como você quis.

**O achado mais importante (e contraintuitivo):** o maior custo **não** é a GPU do OmniParser. É o **token do "cérebro" (LLM)** em cada ação do agente — em todos os tiers ele é o item nº 1, acima da visão. A voz em tempo real é o nº 2 nos planos pesados. Ou seja, a alavanca de margem nº 1 é **rotear para modelos baratos** (nano/mini), não a GPU.

**Boa notícia (§10):** com uma **arquitetura em cascata** — API oficial + regras + modelo pequeno local resolvendo ~80% das ações, e o LLM barato só na geração — esse custo cai **~1/3**, as margens sobem para **74–84%** e o Business sai do vermelho no caso pesado. É a resposta ao "por que usar LLM?": usa-se **pouco**, e só onde ele é insubstituível.

---

## 1. Metodologia e confiança

Cada custo unitário abaixo foi buscado em página oficial (2026) e cruzado com uma segunda fonte quando possível. O custo por cliente é `uso × custo unitário`, somado por componente, em três cenários:

- **Otimizado** — engenharia de custo agressiva (roteador quase todo em modelo nano, browser self-hosted barato, cache de visão alto).
- **Esperado** — operação com disciplina de custo (o alvo realista).
- **Risco** — sem controle (modelo caro, sem cache, voz solta). Serve para mostrar **onde a margem quebra**.

As **premissas de uso** (quantos parses, tokens, minutos de voz por cliente/mês) são **estimativas** — o único jeito honesto de fechá-las é medir num piloto real. Elas estão na §3, explícitas, e são também as **cotas** de cada plano.

---

## 2. Custos unitários pesquisados (2026)

### 2.1 OpenAI — voz, cérebro, transcrição · confiança: ALTA (oficial + 2 fontes)

| Item | Preço | Observação |
|---|---|---|
| Realtime (voz) **gpt-realtime-2.1** | **$32 / $64** por 1M tokens áudio (in/out); cache in $0,40 | ≈ **$0,10–0,20/min** de conversa (derivado; OpenAI não publica por minuto) |
| Realtime **mini** | $10 / $20 por 1M áudio | opção mais barata de voz ao vivo |
| Cérebro flagship **GPT-5.6 Sol / GPT-5.5** | $5 / $30 por 1M | usar só quando precisa |
| Cérebro barato novo **GPT-5.6 Luna** | $1 / $6 por 1M | bom equilíbrio |
| Cérebro **GPT-5.4-mini** | $0,75 / $4,50 por 1M | trabalho de rotina |
| Cérebro **GPT-4.1-nano** | $0,10 / $0,40 por 1M | classificação/triagem barata |
| Transcrição **gpt-4o-mini-transcribe** | **$0,003 / min** | áudio assíncrono (quase de graça) |

*Ressalva honesta:* o **custo por minuto do Realtime** é o número mais mole — é derivado dos tokens (OpenAI cobra por token, não por minuto). Uso **$0,12/min** como esperado, com faixa $0,06–0,25.

### 2.2 GPU + OmniParser · confiança: ALTA (páginas oficiais + model card)

| Item | Valor | Fonte |
|---|---|---|
| GPU L4 (scale-to-zero) | **$0,69–0,80/h** (≈$0,0002/s) | RunPod Serverless / Modal |
| OmniParser v2 — latência | **0,6s/frame (A100), 0,8s (4090)**; ~1–1,5s em GPU média | model card HF |
| OmniParser gerenciado (Replicate, T4) | ~5s/run, **$0,0011/run** | Replicate |
| **Custo por parse (usado no modelo)** | **~$0,0005** (esperado) | L4 s2z, ~1s + overhead |

*Nota:* VRAM ~8–16 GB (24 GB seguro). O **caption (Florence-2) é o gargalo**; a detecção YOLO é ~50ms. Rodar como **serviço externo** já é obrigatório pela licença AGPL (Regra 6).

### 2.3 Browsers server-side · confiança: MÉDIA-ALTA

| Modelo | $/browser-hora | Observação |
|---|---|---|
| **Self-hosted** (Hetzner/AWS) | **$0,008–0,04** | ~1 GB RAM/instância; ~10–30 por VM |
| **Gerenciado** (Browserbase/Steel/Anchor…) | **$0,05–0,12** (+ proxy/CAPTCHA) | cobra **idle** também |

*Insight crítico:* uma sessão **sempre ligada** custa ~$73/mês (gerenciado) vs ~$7/mês (self-hosted). Por isso **hibernar telas ociosas** (sobem sob demanda) é inegociável — está no modelo como "browser-hora ativa", não 24/7.

### 2.4 Infra e câmbio · confiança: ALTA

| Item | Valor |
|---|---|
| Postgres gerenciado | ~$14–25/mês (RDS/Supabase/Neon) — custo fixo de plataforma |
| Object storage R2 | $0,015/GB, **egress $0** (mas só do storage, não do stream ao vivo) |
| Egress ao vivo (AWS) | **$0,09/GB** (mais barato pro Brasil que GCP $0,19/GB) |
| Stream de 1 tela ao vivo | ~0,3–0,9 GB/h → ~**$0,03/tela-hora** |
| **USD→BRL** | **5,16** |

---

## 3. Premissas de uso por tier (estimativa = cotas do plano)

| Uso / mês | Base | Pro | Business |
|---|---|---|---|
| Parses de visão (OmniParser) | 1.500 | 5.000 | 15.000 |
| Ações do agente (chamadas LLM) | 1.500 | 5.000 | 15.000 |
| Browser-horas **ativas** | 15 | 60 | 200 |
| Voz **tempo real** (min) | 0 | 30 | 120 |
| Voz **áudio/transcrição** (min) | 30 | 60 | 120 |
| Telas-hora assistidas ao vivo | 8 | 30 | 100 |

Base = assistente de e-mail (1 conta, sem voz ao vivo). Pro = alguns serviços + voz ao vivo limitada. Business = operação pesada, até 16 telas. **São estimativas** — medir no piloto.

---

## 4. Custo por cliente/mês (COGS)

Valores em **USD** (esperado) e o total em **BRL**. Fonte: `mosaic_custos.py`.

| Componente | Base | Pro | Business |
|---|---|---|---|
| Cérebro (LLM) | 2,25 | 7,50 | **22,50** |
| GPU (visão/OmniParser) | 0,75 | 2,50 | 7,50 |
| Voz tempo real | 0,00 | 3,60 | 14,40 |
| Streaming ao vivo | 0,26 | 0,96 | 3,20 |
| Browsers | 0,22 | 0,90 | 3,00 |
| Voz áudio/transcrição | 0,09 | 0,18 | 0,36 |
| Infra fixa | 0,75 | 0,75 | 0,75 |
| **TOTAL (USD)** | **4,32** | **16,39** | **51,71** |
| **TOTAL (BRL)** | **~22** | **~85** | **~267** |

Faixa completa por cenário (BRL): Base **10 / 22 / 69** · Pro **38 / 85 / 251** · Business **120 / 267 / 784** (otimizado / esperado / risco).

Repare: **cérebro > visão** em todos os tiers. A preocupação com a GPU do OmniParser era menor do que parecia; o que pesa é o token de raciocínio.

---

## 5. Preços recomendados, margem e break-even

Receita líquida = preço − ~12% (gateway + imposto Brasil, estimado).

| Plano | Preço/mês | Margem (esperado) | Margem (risco, sem cap) | Break-even* |
|---|---|---|---|---|
| **Base** | **R$ 97** | **+74%** | +19% | ~10 clientes |
| **Pro** | **R$ 347** | **+72%** | +18% | ~3 clientes |
| **Business** | **R$ 797** | **+62%** | **−12%** | ~1,4 cliente |

\* para cobrir ~US$ 120/mês (~R$ 619) de plataforma fixa.

Leitura honesta: no **caso esperado** as margens são saudáveis (62–74%). No **caso de risco** (cliente pesado sem cota), o **Business fica negativo (−12%)**. Conclusão: **cota + overage não são opcionais** — são o que separa margem de prejuízo.

---

## 6. Overage (excedente da cota) — vender o uso pesado em vez de subsidiá-lo

| Excedente | Custo | Cobrar (~3×) |
|---|---|---|
| +1.000 ações do agente | ~R$ 7,74 | **~R$ 23** |
| +1 min de voz tempo real | ~R$ 0,62 | **~R$ 1,86** |
| +1.000 parses de visão | ~R$ 2,58 | **~R$ 8** |

Assim o cliente que estoura a cota **paga o custo com margem**, em vez de comer a sua.

---

## 7. Sensibilidade — as três alavancas de margem

1. **Roteamento de modelo (a maior).** Cérebro é o item nº 1. Ir de mini/Luna para nano na maioria dos passos derruba o custo do cérebro ~3–4×. É aqui que se ganha ou perde margem.
2. **Voz em tempo real.** ~$0,12/min soma rápido: 120 min = ~R$ 74/mês só de voz. Por isso ela fica nos tiers de cima, com cota e overage.
3. **Cache de visão + browser sob demanda.** Parse-on-change corta chamadas de GPU; hibernar telas corta browser-hora. Ambos mexem no custo, mas menos que o cérebro.

---

## 8. Riscos e ressalvas (não mentir)

- **Uso é estimativa.** Os números da §3 não são medidos — são a minha melhor estimativa. Um **piloto de 2–4 semanas** com 5–10 usuários reais é o que vai calibrar tudo. Trate os preços como **hipótese forte**, não lei.
- **Custo por minuto do Realtime** é o número mais incerto (derivado de tokens). Se a conversa real usar mais áudio de saída, sobe.
- **OmniParser dirigindo webmail real** precisa provar confiabilidade — reprocessos (erro → repetir) multiplicam parses **e** tokens, e podem estourar a estimativa. Validar no piloto.
- **Imposto/gateway (12%)** é uma estimativa; o real depende do regime (Simples/Presumido) e do meio de pagamento.
- **Escala pequena dói:** a plataforma fixa (~R$ 619/mês) só dilui com volume. Nos primeiros clientes, a margem real é menor até passar do break-even.
- **Proxy/CAPTCHA/bloqueio de conta:** automatizar UI de terceiros pode gerar custo extra (proxy) e risco de bloqueio — outro motivo para preferir API oficial onde existir.

---

## 9. Recomendação final

Vender em **R$ 97 / R$ 347 / R$ 797** (Base/Pro/Business), com **cotas embutidas** (= §3) e **overage** (§6). É ticket baixo/médio com **margem bruta saudável (62–74%)** no caso esperado, e o overage protege contra o caso pesado. Três condições para a conta fechar de verdade:

1. **Roteador local-first / modelo barato por padrão** (a alavanca nº 1).
2. **Cotas duras + overage** desde o v1 (sem isso, Business dá prejuízo).
3. **Browser sob demanda + cache de visão** (hibernar ocioso).

E antes de cravar os preços: **rodar o piloto** para medir parses/tokens/minutos reais por cliente. O modelo (`mosaic_custos.py`) recalcula sozinho quando você trocar as premissas.

---

## 10. Atualização — cérebro em cascata (barateia ~1/3)

Como o LLM é o maior custo, a decisão do agente é em **cascata**, parando na primeira camada que resolve: **API oficial do serviço** (Gmail/Graph) → **regras/filtros** → **modelo pequeno próprio no servidor** (na GPU que já roda o OmniParser — no nosso servidor, não no cliente) → **macros determinísticas** → e só então **LLM barato da nuvem**, apenas para **gerar** (resposta, resumo) ou entender pedidos novos. Só ~10–20% das ações chegam ao LLM da nuvem.

Impacto no COGS esperado (mesmo preço, mesma cota):

| Tier | COGS sem cascata | COGS com cascata | Economia | Margem c/ cascata |
|---|---|---|---|---|
| Base | ~R$ 22 | **~R$ 14** | ~37% | **~84%** |
| Pro | ~R$ 85 | **~R$ 57** | ~33% | **~81%** |
| Business | ~R$ 267 | **~R$ 183** | ~31% | **~74%** |

Custo do cérebro por ação cai de **~R$ 0,0077** (LLM em tudo) para **~R$ 0,0022** (cascata, 20% na nuvem). E o **Business deixa de ficar negativo** no cenário de risco (−12% → +12%).

*Trade honesto:* a cascata usa **API por serviço** onde existir (Gmail/Outlook), o que adiciona trabalho de integração. A visão segue **100% OmniParser**; só as ações/leituras estruturadas migram para a API. Recomendado.

---

## 11. Fontes

**OpenAI:** developers.openai.com/api/docs/pricing · openai.com/index/introducing-gpt-realtime/ · openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api/ · aipricing.guru/openai-pricing/ · finout.io/blog/gpt-5.6-pricing-2026-sol-terra-and-luna-tiers-explained · callsphere.ai/blog/vw2c-openai-realtime-cost-per-minute-math-2026
**GPU:** modal.com/pricing · runpod.io/pricing · replicate.com/pricing · baseten.co/pricing · instances.vantage.sh/aws/ec2/g6.xlarge · getdeploying.com/gpus/nvidia-l4
**OmniParser:** huggingface.co/microsoft/OmniParser-v2.0 · microsoft.com/en-us/research/articles/omniparser-v2-turning-any-llm-into-a-computer-use-agent/ · replicate.com/microsoft/omniparser-v2 · github.com/microsoft/OmniParser/issues/187
**Browsers:** browserbase.com/pricing · docs.steel.dev/overview/pricinglimits · docs.anchorbrowser.io/pricing · browserless.io/pricing · instances.vantage.sh/aws/ec2/m7i.2xlarge · costgoat.com/pricing/hetzner · dev.to/atani/16mb-vs-12gb-benchmarking-5-ai-browser-automation-tools-34pm
**Infra/câmbio:** neon.com/pricing · supabase.com/pricing · aws.amazon.com/s3/pricing · developers.cloudflare.com/r2/pricing · cloud.google.com/vpc/network-pricing · open.er-api.com/v6/latest/USD

*Modelo reproduzível em `mosaic_custos.py`. Premissas de uso a validar em piloto. Preços unitários conforme fontes de julho/2026.*
