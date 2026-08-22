"""NOMOS runtime.servico — o runtime persistente governado (NH-014).

O NOMOS sempre foi foreground por decisão ("instale VOCÊ MESMO"). Este módulo
cruza essa linha do único jeito aceitável: o daemon é o MESMO ticker governado
de sempre (autorização POR OCORRÊNCIA, PDP→PEP→boundary→adapter→audit), e a
instalação do serviço é uma mudança de configuração persistente que passa por
gate A5 INTERATIVO — o dono aprova o artefato inteiro (plist impresso na
íntegra + SHA-256), não uma descrição dele.

Invariantes:
- `rodar` RECUSA subir com política corrompida ou localidade ilegível
  (fail-closed; KeepAlive vai reciclar e a recusa fica visível no batimento);
- uma instância só: flock em NOMOS_HOME/servico/servico.lock — a VERDADE é o
  flock (morre com o processo; crash nunca deixa trava presa), o conteúdo do
  arquivo é diagnóstico;
- batimento (NOMOS_HOME/servico/batimento.json) é observabilidade pura:
  NENHUMA decisão o lê — quem decide vivacidade é o flock;
- aprovador do loop é SEMPRE o painel (launchd não tem TTY; um approver
  interativo negaria tudo — correto, mas inoperante); ocorrência sensível sem
  humano no painel EXPIRA NEGADA no TTL — o serviço nunca auto-aprova;
- a pausa (NH-026) vale aqui de graça: o ticker do agendador já consulta
  `pausa.esta_pausado`;
- plist gerado SEM DOCTYPE/URL (prova estática de egress-zero cobre strings
  geradas) e launchctl chamado com argv LITERAL de constantes — nada de
  plano/job/usuário entra no argv.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from nomos.adapters.ticker import CatchUp
from nomos.kernel import pausa
from nomos.kernel.plataforma import chmod_privado
from nomos.kernel.policy import Category, gate

EXIT_OK, EXIT_ERROR, EXIT_DENIED = 0, 1, 3

ROTULO = "br.com.se7enpay.nomos.servico"
DIR_SERVICO = "servico"


@dataclass(frozen=True)
class ConfigServico:
    raizes: tuple[str, ...]
    intervalo_s: float = 1.0
    catchup: CatchUp = CatchUp.RUN_ONCE
    catchup_max: int = 10
    painel: bool = False
    batimento_s: float = 15.0


def _dir(home: Path) -> Path:
    d = Path(home) / DIR_SERVICO
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------- precondições

def verificar_precondicoes(ctx) -> list[str]:
    """Lista de motivos para NÃO subir. Vazia = pode subir.

    Lê `policy.json` CRU de propósito: `PolicyEngine.rules()` degrada para
    deny-all SILENCIOSO quando o arquivo está corrompido — um daemon negando
    tudo para sempre é falso verde. `localidade.esta_ligado()` engole erro
    devolvendo True — aqui a ilegibilidade tem de aparecer com nome.
    `pausa.json` ilegível NÃO impede subir: sobe PAUSADO (o estado seguro
    já existe e o status explica).
    """
    problemas: list[str] = []
    home = Path(ctx["home"])

    p_policy = home / "policy.json"
    if p_policy.exists():
        try:
            dados = json.loads(p_policy.read_bytes())
            if not isinstance(dados, dict):
                problemas.append("policy.json não é um objeto JSON")
            elif not isinstance(dados.get("rules", {}), dict):
                problemas.append("policy.json com 'rules' inválido")
            elif dados.get("rules") == {} and "rules" in dados:
                problemas.append(
                    "policy.json com 'rules' VAZIO — indistinguível de "
                    "corrupção degradada (deny-all silencioso); corrija ou "
                    "remova o arquivo para valer o padrão")
        except Exception:
            problemas.append("policy.json ilegível/corrompida")

    p_loc = home / "localidade.json"
    if p_loc.exists():
        try:
            if not isinstance(json.loads(p_loc.read_text()), dict):
                problemas.append("localidade.json não é um objeto JSON")
        except Exception:
            problemas.append("localidade.json ilegível")

    try:
        ctx["audit"].append("servico.preflight")
    except Exception as exc:
        problemas.append(f"auditoria não gravável ({type(exc).__name__}) — "
                         "sem trilha não há serviço")
    return problemas


# ------------------------------------------------------------ single-instance

class TravaInstancia:
    """flock exclusivo; a autoridade é o LOCK, o conteúdo é diagnóstico."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self._fd: int | None = None

    def adquirir(self) -> bool:
        import fcntl
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.caminho), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        # anti-troca de inode: entre o open e o flock alguém pode ter
        # substituído o arquivo no path — nesse caso travamos um órfão e o
        # path aponta para outro lock. Recusar é mais barato que arbitrar.
        try:
            if os.fstat(fd).st_ino != os.stat(self.caminho).st_ino:
                os.close(fd)
                return False
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({
            "pid": os.getpid(),
            "iniciado_em": datetime.now(timezone.utc).isoformat(),
        }).encode())
        self._fd = fd
        return True

    def liberar(self) -> None:
        if self._fd is not None:
            import fcntl
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def dono(self) -> dict | None:
        try:
            return json.loads(self.caminho.read_text())
        except Exception:
            return None


def _flock_ocupado(caminho: Path) -> bool:
    """Sonda NÃO-destrutiva: consegue travar? Então ninguém roda."""
    import fcntl
    if not Path(caminho).exists():
        return False
    fd = os.open(str(caminho), os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


# ----------------------------------------------------------------- batimento

def escrever_batimento(home: Path, **campos) -> None:
    p = _dir(home) / "batimento.json"
    campos.setdefault("ts", datetime.now(timezone.utc).isoformat())
    campos.setdefault("pid", os.getpid())
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(campos, indent=2, ensure_ascii=False))
    chmod_privado(tmp, 0o600)
    tmp.replace(p)
    chmod_privado(p, 0o600)


def ler_batimento(home: Path) -> dict | None:
    try:
        dados = json.loads((Path(home) / DIR_SERVICO / "batimento.json")
                           .read_text())
        return dados if isinstance(dados, dict) else None
    except Exception:
        return None


# --------------------------------------------------------------------- plist

def caminho_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{ROTULO}.plist"


def gerar_plist(home: Path, exe: str, config: ConfigServico) -> str:
    """launchd LaunchAgent. Sem DOCTYPE e sem URL — precedente de
    `rotinas.exportar`: a prova estática de egress-zero cobre strings geradas."""
    argumentos = [exe, "-m", "nomos.cli", "servico", "rodar"]
    for raiz in config.raizes:
        argumentos += ["--raiz", str(raiz)]
    argumentos += ["--intervalo", str(config.intervalo_s)]
    if config.painel:
        argumentos.append("--painel")
    xml_args = "\n".join(f"    <string>{escape(a)}</string>"
                         for a in argumentos)
    logs = _dir(home)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>{ROTULO}</string>
  <key>ProgramArguments</key>
  <array>
{xml_args}
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>NOMOS_HOME</key><string>{escape(str(home))}</string></dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>{escape(str(logs / 'servico.out.log'))}</string>
  <key>StandardErrorPath</key><string>{escape(str(logs / 'servico.err.log'))}</string>
</dict></plist>
"""


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def _conferir_instalacao(ctx) -> str | None:
    """None = ok/não se aplica; str = motivo da divergência (recusa subir)."""
    registro = Path(ctx["home"]) / DIR_SERVICO / "instalado.json"
    if not registro.exists():
        return None                      # foreground manual: não se aplica
    try:
        dados = json.loads(registro.read_text())
        plist = Path(dados["plist"])
        esperado = dados["plist_sha256"]
    except Exception:
        return "instalado.json ilegível"
    if not plist.exists():
        return f"plist registrado não existe: {plist}"
    real = hashlib.sha256(plist.read_bytes()).hexdigest()
    if real != esperado:
        return "plist DIVERGE do aprovado na instalação (sha não confere)"
    return None


# --------------------------------------------------------------------- rodar

def rodar_servico(ctx, config: ConfigServico, *, max_ticks=None,
                  dormir=None, aprovador=None) -> int:
    """O processo que o launchd supervisiona. Também roda em foreground.

    `aprovador` é injetável SÓ para teste; a superfície do CLI não o expõe —
    em produção é SEMPRE o painel (launchd não tem TTY): registrações e
    ocorrências sensíveis esperam humano no painel e expiram NEGADAS no TTL.
    """
    from nomos.kernel.approvals import ApprovalQueue, panel_approver
    from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador

    home = Path(ctx["home"])
    fila = ApprovalQueue(home / "approvals", audit=ctx["audit"])
    if aprovador is None:
        aprovador = panel_approver(fila)

    problemas = verificar_precondicoes(ctx)
    if problemas:
        ctx["audit"].append("servico.recusou_subir", motivos=problemas)
        escrever_batimento(home, recusado_subir=problemas)
        for m in problemas:
            print(f"NÃO SUBIU: {m}", file=sys.stderr)
        return EXIT_DENIED

    divergencia = _conferir_instalacao(ctx)
    if divergencia:
        ctx["audit"].append("servico.config.divergente", motivo=divergencia)
        escrever_batimento(home, recusado_subir=[divergencia])
        print(f"NÃO SUBIU: {divergencia}", file=sys.stderr)
        return EXIT_DENIED

    trava = TravaInstancia(_dir(home) / "servico.lock")
    if not trava.adquirir():
        dono = trava.dono() or {}
        ctx["audit"].append("servico.instancia_duplicada",
                            pid_dono=dono.get("pid"))
        print(f"já existe um serviço vivo (pid {dono.get('pid', '?')}) — "
              "uma instância só.", file=sys.stderr)
        return EXIT_ERROR

    painel_srv = None
    try:
        ag = AgendadorGovernado(ctx, aprovador, ConfigAgendador(
            raizes=config.raizes, catchup=config.catchup,
            catchup_max=config.catchup_max, intervalo_s=config.intervalo_s))
        try:
            # devolve os NOMES das capacidades alcançáveis; falha = exceção
            ag.preparar()
        except Exception as exc:
            motivo = f"preparar: {type(exc).__name__}: {exc}"
            ctx["audit"].append("servico.preparar.falhou",
                                erro=type(exc).__name__)
            escrever_batimento(home, recusado_subir=[motivo])
            print(f"NÃO SUBIU: {motivo}", file=sys.stderr)
            return EXIT_DENIED

        if config.painel:
            from nomos.interface.panel import PanelServer
            painel_srv = PanelServer(fila)
            painel_srv.start()
            print(f"painel de aprovações: {painel_srv.url}")

        caixa = {"ticks": 0, "executadas": 0, "negadas": 0, "falhas": 0,
                 "puladas": 0, "ultimo_batimento": 0.0, "pausado": False}

        def _bater(forcado=False):
            agora = time.monotonic()
            pausado = pausa.esta_pausado(home)
            trocou = pausado != caixa["pausado"]
            caixa["pausado"] = pausado
            if (not forcado and not trocou
                    and agora - caixa["ultimo_batimento"] < config.batimento_s):
                return
            caixa["ultimo_batimento"] = agora
            escrever_batimento(
                home, ticks=caixa["ticks"], executadas=caixa["executadas"],
                negadas=caixa["negadas"], falhas=caixa["falhas"],
                puladas=caixa["puladas"], pausado=pausado,
                intervalo_s=config.intervalo_s, versao=1)

        dormir_real = dormir or time.sleep

        def _dormir_com_batimento(segundos):
            _bater()
            dormir_real(segundos)

        ticker = ag.ticker(dormir=_dormir_com_batimento)
        tick_original = ticker.tick

        def _tick_contado():
            r = tick_original()
            caixa["ticks"] += 1
            caixa["executadas"] += r.executadas
            caixa["negadas"] += r.negadas
            caixa["falhas"] += r.falhas
            caixa["puladas"] += r.puladas
            return r

        ticker.tick = _tick_contado

        import signal as _sig

        def _parar(_s, _f):
            ticker.parar()

        for numero in (_sig.SIGINT, _sig.SIGTERM):
            try:
                _sig.signal(numero, _parar)
            except (ValueError, OSError, AttributeError):
                pass                     # thread secundária/SO sem o sinal

        ctx["audit"].append("servico.iniciado", raizes=list(config.raizes),
                            intervalo_s=config.intervalo_s,
                            painel=config.painel)
        _bater(forcado=True)
        ticker.rodar_ate(max_ticks=max_ticks)

        ctx["audit"].append("servico.encerrado", **{
            k: caixa[k] for k in
            ("ticks", "executadas", "negadas", "falhas", "puladas")})
        escrever_batimento(
            home, encerrado=True, ticks=caixa["ticks"],
            executadas=caixa["executadas"], negadas=caixa["negadas"],
            falhas=caixa["falhas"], puladas=caixa["puladas"],
            pausado=pausa.esta_pausado(home),
            intervalo_s=config.intervalo_s, versao=1)
        if caixa["falhas"]:
            return EXIT_DENIED
        return EXIT_OK if caixa["negadas"] == 0 else EXIT_DENIED
    finally:
        if painel_srv is not None:
            painel_srv.stop()
        trava.liberar()


# --------------------------------------------------------- instalar/remover

_ARGV_BOOTSTRAP = ("/bin/launchctl", "bootstrap")
_ARGV_BOOTOUT = ("/bin/launchctl", "bootout")


def _executar_padrao(argv) -> int:
    import subprocess
    return subprocess.run(list(argv), check=False).returncode


def instalar(ctx, config: ConfigServico, aprovador, *, executar=None,
             simular=False) -> int:
    """Instala o LaunchAgent — gate A5 INTERATIVO, dono aprova o artefato."""
    if sys.platform != "darwin" and not simular:
        print("instalação automática só existe no macOS (launchd). Noutros "
              "sistemas use `nomos rotinas exportar` como molde e instale "
              "você mesmo.", file=sys.stderr)
        return EXIT_ERROR

    problemas = verificar_precondicoes(ctx)
    if problemas:
        for m in problemas:
            print(f"NÃO INSTALO: {m}", file=sys.stderr)
        return EXIT_DENIED

    home = Path(ctx["home"])
    exe = sys.executable
    plist_texto = gerar_plist(home, exe, config)
    sha = _sha256(plist_texto)
    destino = caminho_plist()
    argv = list(_ARGV_BOOTSTRAP) + [f"gui/{os.getuid()}", str(destino)]

    print("── plist a instalar (na ÍNTEGRA — você aprova o artefato) ──")
    print(plist_texto)
    print(f"SHA-256: {sha}")
    print(f"destino: {destino}")
    print(f"launchctl: {' '.join(argv)}")
    if simular:
        print("(simulação: nada foi escrito, launchctl não foi chamado)")
        return EXIT_OK

    decisao = ctx["policy"].decide(Category.CODE_EXEC,
                                   target=f"launchd:instalar:{ROTULO}")
    if not gate(decisao, aprovador):
        ctx["audit"].append("servico.instalar.negado", sha256=sha)
        print("instalação NÃO aprovada (fail-closed).", file=sys.stderr)
        return EXIT_DENIED
    ctx["audit"].append("servico.instalar.aprovado", sha256=sha,
                        destino=str(destino))

    registro = _dir(home) / "instalado.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(plist_texto)
    os.chmod(tmp, 0o644)
    tmp.replace(destino)
    dados = {"plist": str(destino), "plist_sha256": sha,
             "raizes": list(config.raizes),
             "intervalo_s": config.intervalo_s, "painel": config.painel,
             "instalado_em": datetime.now(timezone.utc).isoformat()}
    tmp_r = registro.with_suffix(".tmp")
    tmp_r.write_text(json.dumps(dados, indent=2, ensure_ascii=False))
    chmod_privado(tmp_r, 0o600)
    tmp_r.replace(registro)
    chmod_privado(registro, 0o600)

    rc = (executar or _executar_padrao)(argv)
    if rc != 0:
        destino.unlink(missing_ok=True)
        registro.unlink(missing_ok=True)
        ctx["audit"].append("servico.instalar.falhou", rc=rc)
        print(f"launchctl falhou (rc={rc}) — rollback: plist e registro "
              "removidos.", file=sys.stderr)
        return EXIT_ERROR
    ctx["audit"].append("servico.instalado", plist_sha256=sha,
                        raizes=list(config.raizes), rc=rc)
    print("serviço instalado e carregado (KeepAlive).")
    return EXIT_OK


def remover(ctx, aprovador, *, executar=None, simular=False) -> int:
    """Remove o LaunchAgent — gate A1 (reduz autoridade, mas toca fora do
    NOMOS_HOME e segue interativo+auditado). Idempotente."""
    destino = caminho_plist()
    argv = list(_ARGV_BOOTOUT) + [f"gui/{os.getuid()}/{ROTULO}"]
    if simular:
        print(f"(simulação) launchctl: {' '.join(argv)}")
        print(f"(simulação) apagaria: {destino}")
        return EXIT_OK
    if sys.platform != "darwin":
        print("remoção automática só existe no macOS.", file=sys.stderr)
        return EXIT_ERROR

    decisao = ctx["policy"].decide(Category.WRITE_LOCAL,
                                   target=f"launchd:remover:{ROTULO}")
    if not gate(decisao, aprovador):
        ctx["audit"].append("servico.remover.negado")
        print("remoção NÃO aprovada (fail-closed).", file=sys.stderr)
        return EXIT_DENIED

    (executar or _executar_padrao)(argv)   # bootout de serviço ausente: ok
    if destino.exists():
        # só apaga se o Label for NOSSO — nunca o plist alheio
        try:
            import plistlib
            label = plistlib.loads(destino.read_bytes()).get("Label")
        except Exception:
            label = None
        if label == ROTULO:
            destino.unlink()
        else:
            print(f"NÃO apaguei {destino}: Label {label!r} não é {ROTULO!r}",
                  file=sys.stderr)
    (Path(ctx["home"]) / DIR_SERVICO / "instalado.json").unlink(missing_ok=True)
    ctx["audit"].append("servico.removido")
    print("serviço removido.")
    return EXIT_OK


# -------------------------------------------------------------------- status

def diagnostico(ctx) -> dict:
    """Testável sem launchd. Vivo = flock ocupado E batimento fresco —
    PID nunca prova nada (reuso), batimento sozinho pode ser forjado."""
    home = Path(ctx["home"])
    registro = home / DIR_SERVICO / "instalado.json"
    bat = ler_batimento(home)
    intervalo = float((bat or {}).get("intervalo_s") or 60.0)
    fresco = False
    if bat and bat.get("ts"):
        try:
            idade = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(bat["ts"])).total_seconds()
            fresco = idade < 3 * max(intervalo, 15.0)
        except Exception:
            fresco = False
    ocupado = _flock_ocupado(home / DIR_SERVICO / "servico.lock")
    from nomos.runtime.agendador import caminho_do_armazem
    from nomos.adapters.scheduler import ArmazemJobs
    try:
        ilegiveis = ArmazemJobs(caminho_do_armazem(home)).ilegiveis()
    except Exception:
        ilegiveis = {}
    return {
        "instalado": registro.exists(),
        "plist_sha_confere": _conferir_instalacao(ctx) is None,
        "rodando": ocupado and fresco,
        "flock_ocupado": ocupado,
        "batimento": bat,
        "batimento_fresco": fresco,
        "pausa": pausa.estado(home),
        "problemas": verificar_precondicoes(ctx),
        "jobs_ilegiveis": ilegiveis,
        "recusado_subir": (bat or {}).get("recusado_subir"),
    }


def status(ctx) -> int:
    d = diagnostico(ctx)
    print(f"instalado: {'sim' if d['instalado'] else 'não'}"
          + ("" if d["plist_sha_confere"] else "  ⚠ plist DIVERGE do aprovado"))
    vivo = "VIVO" if d["rodando"] else (
        "flock ocupado, batimento velho (loop travado?)" if d["flock_ocupado"]
        else "parado")
    print(f"processo: {vivo}")
    if d["batimento"]:
        b = d["batimento"]
        print(f"batimento: ts={b.get('ts')} ticks={b.get('ticks')} "
              f"executadas={b.get('executadas')} negadas={b.get('negadas')} "
              f"falhas={b.get('falhas')} pausado={b.get('pausado')}")
    if d["recusado_subir"]:
        print(f"última recusa de subida: {d['recusado_subir']}")
    p = d["pausa"]
    print("pausa: " + ("ATIVA" if p["pausado"] else "inativa")
          + (" (pausa.json ilegível)" if p.get("ilegivel") else ""))
    for m in d["problemas"]:
        print(f"problema: {m}")
    if d["jobs_ilegiveis"]:
        print(f"jobs ilegíveis no armazém: {len(d['jobs_ilegiveis'])}")
    return EXIT_OK
