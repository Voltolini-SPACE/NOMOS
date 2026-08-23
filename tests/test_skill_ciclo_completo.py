"""O ciclo criar → catálogo → instalar → listar, provado de ponta a ponta.

Existiam testes das PARTES, e todos passavam — mas o ciclo estava quebrado no
meio: `adicionar_ao_catalogo` não tinha nenhum chamador de produção (só dois
testes), então o catálogo tinha leitor e nenhum escritor e a lista de "skills
disponíveis para instalar" nascia sempre vazia. Teste de parte não pega isso;
só o ciclo pega. Daí este arquivo.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from nomos.ext import skill_catalogo as scat
from nomos.ext import skill_registry as reg
from nomos.kernel.policy import PolicyEngine


def _skill_em(pasta, nome, permissions=None):
    d = pasta / nome
    d.mkdir(parents=True)
    corpo = f'print("sou {nome}")\n'
    (d / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    (d / "skill.json").write_text(json.dumps({
        "name": nome, "version": "1.0.0",
        "description": f"skill {nome}",
        "permissions": permissions or ["A0_READ_LOCAL"],
        "entry": "main.py",
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()},
    }))
    return d


# --------------------------------------------------------------- semeadura
def test_catalogo_nasce_vazio_sem_semear(nomos_home):
    """O estado que o dono via: nada para instalar, sem caminho para encher."""
    assert reg.catalogo(nomos_home) == []
    assert scat.capacidades(nomos_home, nomos_home / "skills") == []


def test_semear_da_ao_catalogo_o_escritor_que_faltava(tmp_path, nomos_home):
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    _skill_em(origem, "beta")

    res = reg.semear_catalogo(nomos_home, origem)

    assert sorted(res["adicionadas"]) == ["alfa", "beta"]
    assert res["erros"] == []
    assert sorted(s["name"] for s in reg.catalogo(nomos_home)) == ["alfa", "beta"]


def test_semear_e_idempotente(tmp_path, nomos_home):
    """Semear duas vezes não duplica — upsert por nome."""
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    reg.semear_catalogo(nomos_home, origem)
    reg.semear_catalogo(nomos_home, origem)
    assert len(reg.catalogo(nomos_home)) == 1


def test_manifesto_quebrado_nao_derruba_os_bons(tmp_path, nomos_home):
    origem = tmp_path / "loja"
    _skill_em(origem, "boa")
    ruim = origem / "ruim"
    ruim.mkdir()
    (ruim / "skill.json").write_text("{ isto não é json")

    res = reg.semear_catalogo(nomos_home, origem)

    assert res["adicionadas"] == ["boa"]
    assert [p for p, _ in res["erros"]] == ["ruim"]


def test_semear_pasta_inexistente_falha_limpo(tmp_path, nomos_home):
    with pytest.raises(reg.RegistroError):
        reg.semear_catalogo(nomos_home, tmp_path / "nao-existe")


# ------------------------------------------------------------- ciclo todo
def test_ciclo_completo_disponivel_vira_instalada(tmp_path, nomos_home):
    """semear → aparece DISPONÍVEL → instalar → aparece INSTALADA.

    É o percurso que o dono faz na página de skills, inteiro.
    """
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    _skill_em(origem, "beta")
    skills_dir = nomos_home / "skills"

    # 1) semear: as duas ficam visíveis, nenhuma instalada
    reg.semear_catalogo(nomos_home, origem)
    caps = {c["nome"]: c["status"] for c in scat.capacidades(nomos_home, skills_dir)}
    assert caps == {"alfa": "disponível no catálogo", "beta": "disponível no catálogo"}

    # 2) instalar UMA, pelo mesmo caminho do CLI (gate + confirmação)
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(origem / "alfa", skills_dir, engine, lambda d: True,
                 confirmar_experimental=lambda mf: True)

    # 3) o status VIRA, e a outra continua disponível
    caps = {c["nome"]: c["status"] for c in scat.capacidades(nomos_home, skills_dir)}
    assert caps["alfa"] == "instalada"
    assert caps["beta"] == "disponível no catálogo"

    # 4) `disponiveis` para de oferecer o que já está instalado
    assert [d["name"] for d in reg.disponiveis(nomos_home, skills_dir)] == ["beta"]


def test_semear_nao_afrouxa_o_gate(tmp_path, nomos_home):
    """Constar no catálogo é ficar VISÍVEL, não ficar autorizado.

    Se semear virasse permissão implícita, a semeadura seria um bypass do A5.
    """
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    reg.semear_catalogo(nomos_home, origem)

    engine = PolicyEngine(nomos_home / "policy.json")
    # ATENÇÃO ao tipo: as duas recusas levantam exceções IRMÃS e não
    # relacionadas — `RegistroError` (registry) e `SkillError` (skills). Quem
    # consome tem de pegar as duas; a produção faz isso em
    # `simple/skills_menu.py:156`, com a tupla. Não "simplifique" para uma só.
    from nomos.ext.skills import SkillError

    # sem confirmador de experimental: recusa mesmo estando no catálogo
    with pytest.raises(reg.RegistroError):
        reg.instalar(origem / "alfa", nomos_home / "skills", engine, lambda d: True)
    # sem aprovação no gate A5: recusa também
    with pytest.raises(SkillError):
        reg.instalar(origem / "alfa", nomos_home / "skills", engine, lambda d: False,
                     confirmar_experimental=lambda mf: True)
    # e nada foi instalado por nenhum dos dois caminhos
    assert not (nomos_home / "skills" / "alfa").exists()


def test_semeado_entra_NAO_assinado(tmp_path, nomos_home):
    """A semeadura local não pode fingir procedência: nada de assinatura."""
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    reg.semear_catalogo(nomos_home, origem)

    _, assinado, _ = reg.catalogo_info(nomos_home)
    assert assinado is False
    assert all("signature" not in s for s in reg.catalogo(nomos_home))


# ------------------------------------------------- dependências declaradas
def _com_requires(pasta, nome, requires):
    d = _skill_em(pasta, nome)
    mf = json.loads((d / "skill.json").read_text())
    mf["requires"] = requires
    (d / "skill.json").write_text(json.dumps(mf))
    return d


def test_binario_ausente_recusa_na_instalacao(tmp_path, nomos_home):
    """O ponto do "plug-and-play": recusar AGORA, não quebrar no uso."""
    src = _com_requires(tmp_path / "loja", "precisa-bin", [
        {"tipo": "binario", "nome": "binario-que-nao-existe-xyz", "obrigatorio": True}])
    engine = PolicyEngine(nomos_home / "policy.json")

    with pytest.raises(reg.RegistroError, match="não existe nesta máquina"):
        reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                     confirmar_experimental=lambda m: True, home=nomos_home)
    assert not (nomos_home / "skills" / "precisa-bin").exists()


def test_binario_presente_instala(tmp_path, nomos_home):
    src = _com_requires(tmp_path / "loja", "precisa-sh", [
        {"tipo": "binario", "nome": "sh", "obrigatorio": True}])
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)
    assert (nomos_home / "skills" / "precisa-sh").exists()


def test_dependencia_opcional_nao_bloqueia(tmp_path, nomos_home):
    src = _com_requires(tmp_path / "loja", "opcional", [
        {"tipo": "binario", "nome": "nao-existe-xyz", "obrigatorio": False}])
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)
    assert (nomos_home / "skills" / "opcional").exists()


def test_binario_como_linha_de_comando_usa_o_primeiro_token(nomos_home):
    """`python3 -m feedparser` não é um executável: o que existe é `python3`.

    Medir a linha inteira com `which` reprovaria SEMPRE — recusa inventada.
    """
    mf = {"requires": [{"tipo": "binario", "nome": "sh -c algo", "obrigatorio": True}]}
    assert reg.verificar_requisitos(mf, nomos_home) == []


def test_nome_em_prosa_nao_vira_ausencia(nomos_home):
    """Nome não consultável ⇒ NÃO VERIFICADO, e não bloqueia.

    Bloquear por ignorância inventa impedimento e empurra o autor a apagar o
    `requires` — o oposto do que queremos. Só evidência de ausência bloqueia.
    """
    mf = {"requires": [{"tipo": "chave",
                        "nome": "token do gh (host, nao do cofre)",
                        "obrigatorio": True}]}
    itens = reg.verificar_requisitos(mf, nomos_home)
    assert len(itens) == 1
    assert itens[0]["verificado"] is False


def test_tipo_desconhecido_avisa_sem_bloquear(tmp_path, nomos_home):
    src = _com_requires(tmp_path / "loja", "tipo-novo", [
        {"tipo": "coisa-que-nao-existe", "nome": "x", "obrigatorio": True}])
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)
    assert (nomos_home / "skills" / "tipo-novo").exists()


def test_chave_ausente_no_cofre_e_evidencia_e_bloqueia(tmp_path, nomos_home):
    """Nome CONSULTÁVEL e ausente do cofre é evidência — aí sim bloqueia."""
    src = _com_requires(tmp_path / "loja", "precisa-chave", [
        {"tipo": "chave", "nome": "groq_api_key", "obrigatorio": True}])
    engine = PolicyEngine(nomos_home / "policy.json")
    with pytest.raises(reg.RegistroError):
        reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                     confirmar_experimental=lambda m: True, home=nomos_home)


def test_sem_requires_comporta_como_antes(tmp_path, nomos_home):
    """Manifesto sem `requires` não muda de comportamento (compatibilidade)."""
    src = _skill_em(tmp_path / "loja", "sem-requires")
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)
    assert (nomos_home / "skills" / "sem-requires").exists()


# ------------------------------------------------ origem que sempre existe
def test_semear_do_pacote_funciona_fora_do_checkout(nomos_home, monkeypatch):
    """O `--semear` sem PASTA usa as skills EMBUTIDAS no pacote.

    Antes, o CLI sugeria `nomos skills instalar examples/skills/busca-arquivos`
    — caminho que só existe dentro do checkout. Medido no pacote instalado do
    dono: `(pacote)/examples` → False. Numa instalação normal não havia de onde
    instalar nada: o "plug-and-play" não tinha origem.
    """
    from nomos import skills_embutidas as emb

    embutido = emb.diretorio_embutido()
    assert (embutido / "busca-arquivos" / "skill.json").is_file()

    res = reg.semear_catalogo(nomos_home, embutido)

    assert len(res["adicionadas"]) >= 4
    nomes = {s["name"] for s in reg.catalogo(nomos_home)}
    assert {"busca-arquivos", "lembrete", "organizador", "sistema-info"} <= nomes


# --------------------------------------------- honestidade sobre execução
def test_modulo_python_presente_passa(nomos_home):
    mf = {"requires": [{"tipo": "modulo_python", "nome": "json",
                        "obrigatorio": True}]}
    assert reg.verificar_requisitos(mf, nomos_home) == []


def test_skill_sem_rede_avisa_que_nao_executa_no_mac(nomos_home, monkeypatch):
    """A mais segura (A0) é justamente a que não executa: o dono tem de saber."""
    from nomos.kernel import plataforma
    monkeypatch.setattr(plataforma, "execucao_isolada_disponivel", lambda: False)
    pode, motivo = reg.pode_executar_aqui(
        {"permissions": ["A0_READ_LOCAL"]}, nomos_home)
    assert pode is False
    assert "só-Linux por desenho" in motivo


def test_skill_com_rede_avisa_cadeado_ligado(nomos_home):
    """Com A2 e cadeado ligado, também não executa — e por outro motivo."""
    from nomos.kernel import localidade
    localidade.definir(nomos_home, ligado=True)
    pode, motivo = reg.pode_executar_aqui(
        {"permissions": ["A0_READ_LOCAL", "A2_NET_EGRESS"]}, nomos_home)
    assert pode is False
    assert "nomos local off" in motivo


def test_aviso_nao_bloqueia_a_instalacao(tmp_path, nomos_home, monkeypatch):
    """Dizer a verdade não é recusar: a skill instala mesmo sem poder rodar."""
    from nomos.kernel import plataforma
    monkeypatch.setattr(plataforma, "execucao_isolada_disponivel", lambda: False)
    src = _skill_em(tmp_path / "loja", "so-instala")
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)
    assert (nomos_home / "skills" / "so-instala").exists()


# ------------------------------- o previsor não pode divergir do executor
@pytest.mark.parametrize("perms,cadeado", [
    (["A0_READ_LOCAL"], False),
    (["A0_READ_LOCAL", "A2_NET_EGRESS"], True),
    (["A0_READ_LOCAL", "A2_NET_EGRESS"], False),
])
def test_aviso_de_execucao_bate_com_a_execucao_real(tmp_path, nomos_home,
                                                    perms, cadeado):
    """`pode_executar_aqui` promete; `executar` cumpre. Os dois têm de bater.

    O aviso existe para o dono não descobrir no primeiro uso — mas um aviso que
    diverge do executor é PIOR que nenhum: mente com autoridade. Esta asserção
    é independente de plataforma de propósito (no Linux o ramo sem rede executa,
    no macOS não), porque o que se afirma é a COERÊNCIA, não o resultado.

    PRECISÃO: `pode_executar_aqui` responde "a PLATAFORMA deixa rodar?", não
    "a skill vai dar certo". Por isso a skill usada aqui sempre sai com 0 —
    uma que falhe por conta própria (argumento faltando, por exemplo) daria
    rc≠0 com `pode=True` sem que houvesse divergência nenhuma.
    """
    from nomos.kernel import localidade

    localidade.definir(nomos_home, ligado=cadeado)
    src = _skill_em(tmp_path / "loja", "coerente", permissions=perms)
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)

    mf = json.loads((src / "skill.json").read_text())
    pode, _motivo = reg.pode_executar_aqui(mf, nomos_home)
    rc, _saida = reg.executar("coerente", nomos_home / "skills", engine,
                              lambda d: True)

    assert pode == (rc == 0), (
        f"previsor disse pode={pode} mas executar deu rc={rc}")


# ------------------------------- ver o que veio na caixa, sem comando nenhum
def test_home_vazia_ve_as_do_pacote_sem_registrar(nomos_home):
    """Instalação nova mostra o que veio no wheel — e NÃO escreve nada.

    Antes, uma home nova dizia "nenhuma skill disponível ainda" tendo 33 dentro
    do próprio pacote: só apareciam depois de alguém rodar `--semear`. Exigir um
    comando para ENXERGAR o que já veio na caixa é o oposto de plug-and-play.

    A fronteira que este teste protege: mostrar NÃO é registrar nem autorizar.
    """
    caps = scat.capacidades(nomos_home, nomos_home / "skills",
                            incluir_do_pacote=True)

    assert caps, "home nova deveria enxergar as skills do pacote"
    assert all(c["status"] == "vem no NOMOS" for c in caps)
    assert not (nomos_home / "registry" / "catalogo.json").exists(), \
        "listar não pode escrever no registro"
    assert reg.catalogo(nomos_home) == []


def test_fonte_do_pacote_e_opt_in(nomos_home):
    """O default preserva o contrato antigo: home vazia -> lista vazia.

    Duas suítes afirmam isso; mudar por baixo quebraria quem as escreveu.
    """
    assert scat.capacidades(nomos_home, nomos_home / "skills") == []


def test_instalada_vence_a_do_pacote(tmp_path, nomos_home):
    """Skill instalada não aparece duas vezes por também vir no pacote."""
    src = _skill_em(tmp_path / "loja", "busca-arquivos")
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)

    caps = scat.capacidades(nomos_home, nomos_home / "skills",
                            incluir_do_pacote=True)
    achadas = [c for c in caps if c["nome"] == "busca-arquivos"]
    assert len(achadas) == 1 and achadas[0]["status"] == "instalada"



def test_modulo_confirma_presenca_mas_nao_bloqueia_por_ausencia(nomos_home):
    """Assimetria deliberada, e ela decide o comportamento.

    Binário se acha por caminho, então ausência é EVIDÊNCIA e bloqueia. Módulo
    não: saber se existe no interpretador que a cerca usa exigiria RODAR aquele
    interpretador. Duas saídas foram descartadas — `find_spec` no processo atual
    mede o interpretador ERRADO (recusou `reach-rss` com feedparser presente em
    /opt/homebrew/bin/python3), e sondar por `subprocess` poria geração de
    processo no NÚCLEO, fora do supervisor, que é garantia estrutural do produto.
    """
    # presente aqui => evidência de presença, não bloqueia
    assert reg.verificar_requisitos(
        {"requires": [{"tipo": "modulo_python", "nome": "json",
                       "obrigatorio": True}]}, nomos_home) == []

    # ausente aqui => NÃO VERIFICÁVEL, aparece como aviso e não bloqueia
    faltam = reg.verificar_requisitos(
        {"requires": [{"tipo": "modulo_python", "nome": "modulo_zzz_inexistente",
                       "obrigatorio": True}]}, nomos_home)
    assert len(faltam) == 1
    assert faltam[0]["verificado"] is False
    assert "outro interpretador" in faltam[0]["motivo"]


def test_modulo_ausente_nao_impede_instalacao(tmp_path, nomos_home):
    """O caso real: `reach-rss` era RECUSADA por feedparser "ausente"."""
    src = _com_requires(tmp_path / "loja", "usa-modulo", [
        {"tipo": "modulo_python", "nome": "modulo_zzz_inexistente",
         "obrigatorio": True}])
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)
    assert (nomos_home / "skills" / "usa-modulo").exists()


# ---------------------------------------- argumentos atravessam a cerca
def test_regras_da_cerca_cobrem_TODOS_os_argumentos_arquivo(tmp_path):
    """Regressão do `break` que cegava o segundo argumento.

    O executor passa DOIS arquivos ao interpretador: o entry (argv[1]) e o
    `skill-args-*.json` (argv[2]). O laço que emite as regras de leitura
    parava no primeiro — medido em 23/08: toda skill chamada COM argumentos
    morria em "não li os argumentos de '…/skill-args-….json'", com a cerca
    deixando ler o script e negando o JSON logo ao lado.
    """
    from nomos.runtime.sandbox import _regras_do_interpretador

    a = tmp_path / "dir-a" / "entry.py"
    b = tmp_path / "dir-b" / "args.json"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_text("pass")
    b.write_text("{}")

    _argv, regras = _regras_do_interpretador(["python3", str(a), str(b)])
    texto = "\n".join(regras)
    assert str(a.parent) in texto, "diretório do entry tem de entrar"
    assert str(b.parent) in texto, "diretório do args TAMBÉM — era o furo"


def test_argumentos_chegam_na_skill_de_ponta_a_ponta(tmp_path, nomos_home):
    """O ciclo inteiro: executar(argumentos=...) → a skill LÊ e devolve.

    A skill ecoa o que recebeu; a asserção é o round-trip. Declara A2 para
    exercitar o caminho que executa nas duas plataformas (no macOS o ramo sem
    rede é recusado por desenho) — o gate é aprovado pelo stub do teste.
    """
    from nomos.kernel import localidade

    localidade.definir(nomos_home, ligado=False)
    corpo = (
        "import json, sys\n"
        "args = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else {}\n"
        "print(json.dumps({'ok': True, 'eco': args}))\n")
    d = tmp_path / "loja" / "eco"
    d.mkdir(parents=True)
    (d / "main.py").write_text(corpo)
    (d / "skill.json").write_text(json.dumps({
        "name": "eco", "version": "1.0.0", "entry": "main.py",
        "permissions": ["A0_READ_LOCAL", "A2_NET_EGRESS"],
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}))
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(d, nomos_home / "skills", engine, lambda x: True,
                 confirmar_experimental=lambda m: True, home=nomos_home)

    rc, j, bruta = reg.executar_json(
        "eco", nomos_home / "skills", engine, lambda x: True,
        argumentos={"mensagem": "atravessei a cerca", "n": 7})

    assert rc == 0, bruta
    assert j and j["eco"] == {"mensagem": "atravessei a cerca", "n": 7}
