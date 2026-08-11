/* NOMOS — filtro governado SINTÉTICO, binário nativo purpose-built.
 *
 * Existe porque A5.5 mediu que as outras duas rotas estão fechadas neste host:
 *   script            -> exige o interpretador na allowlist = reabre shell
 *   binário do SO     -> SIGKILL ao ser copiado (arm64 perde platform binary),
 *                        e nem ad-hoc signing resolve
 * Binário NÃO-de-sistema copiado para o armazém executa (medido).
 *
 * Transformação legítima: SENHA=<algo> -> SENHA=REDIGIDO
 *
 * As sondas existem AQUI dentro, compiladas, porque o filtro não pode chamar
 * sh/python/node para testar uma fronteira — isso seria o próprio escape que
 * A5.5 proíbe. Quem escolhe a sonda é a POLÍTICA (argv governado por A5.4),
 * nunca o repositório.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

static int prova(const char *rot, int ok) {
    printf("%s=%s\n", rot, ok ? "ALCANCEI" : "NEGADO");
    return ok;
}

/* ─────────────────── sondas de CICLO DE VIDA (A5.6) ──────────────────────
 *
 * Descendente aqui é sempre por `fork`, nunca por exec de outro programa: a
 * allowlist de exec do filtro tem UM literal só (o próprio artefato), e é isso
 * que A5.5 congelou. Fork continua permitido de propósito — removê-lo foi
 * medido e faz `git commit` devolver rc=0 com "cannot fork() for maintenance",
 * degradação silenciosa.
 *
 * Cada processo criado GRAVA UM MARCADOR com o próprio pid antes de dormir.
 * O marcador é o controle positivo do teste de kill: sem ele, "não sobrou
 * processo" não se distingue de "nunca houve processo", e a bateria inteira
 * seria vácuo. O teste lê os pids do disco e exige que TENHAM EXISTIDO e
 * estejam mortos depois. */
static void marcar(const char *dir, const char *papel, pid_t pid) {
    char caminho[4096];
    snprintf(caminho, sizeof caminho, "%s/%s.%d", dir, papel, (int)pid);
    FILE *f = fopen(caminho, "w");
    if (f) { fprintf(f, "%d\n", (int)pid); fclose(f); }
}

/* Marca, avisa no stdout e dorme. O flush é obrigatório: sem ele o buffer
 * morre junto com a imagem quando o SIGKILL chega, e o teste perderia a prova
 * de que o processo chegou a existir. */
static int marcar_e_dormir(const char *dir, const char *papel, int seg) {
    marcar(dir, papel, getpid());
    printf("%s_VIVO=%d\n", papel, (int)getpid());
    fflush(stdout);
    sleep(seg);
    printf("%s_ACORDOU=%d\n", papel, (int)getpid());
    fflush(stdout);
    return 0;
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--sonda-leitura") == 0) {
        FILE *f = fopen(argv[2], "r");
        if (f) fclose(f);
        return prova("LEITURA", f != NULL) ? 0 : 1;
    }
    if (argc > 1 && strcmp(argv[1], "--sonda-escrita") == 0) {
        FILE *f = fopen(argv[2], "w");
        if (f) { fputs("PLANTADO\n", f); fclose(f); }
        return prova("ESCRITA", f != NULL) ? 0 : 1;
    }
    if (argc > 1 && strcmp(argv[1], "--sonda-rede") == 0) {
        int s = socket(AF_INET, SOCK_STREAM, 0);
        if (s < 0) return prova("REDE", 0) ? 0 : 1;
        struct sockaddr_in a; memset(&a, 0, sizeof a);
        /* Alvo vem da POLÍTICA (argv), nunca fixo: o controle positivo
         * precisa de um destino que ACEITE conexão neste host, senão o
         * DENIED do sandbox não se distingue de "não havia rede". */
        a.sin_family = AF_INET;
        a.sin_port = htons((unsigned short)atoi(argc > 3 ? argv[3] : "80"));
        a.sin_addr.s_addr = inet_addr(argc > 2 ? argv[2] : "1.1.1.1");
        int ok = connect(s, (struct sockaddr *)&a, sizeof a) == 0;
        close(s);
        return prova("REDE", ok) ? 0 : 1;
    }
    if (argc > 1 && strcmp(argv[1], "--sonda-env") == 0) {
        const char *v = getenv(argv[2]);
        printf("ENV_%s=%s\n", argv[2], v ? v : "(ausente)");
        return v ? 0 : 1;
    }
    if (argc > 1 && strcmp(argv[1], "--sonda-dorme") == 0) {
        /* Lê stdin ATÉ O FIM e só então dorme. Existe para medir o prazo com
         * stdin ligado. Um shell script não serve como sonda aqui: exigiria o
         * interpretador na allowlist de exec, que é exatamente o que A5.5
         * fechou — o sandbox recusa a troca de imagem para a variante do shell.
         * A sonda de prazo tem de ser nativa pelo mesmo motivo que o filtro
         * tem de ser nativo. */
        char buf[4096];
        while (fread(buf, 1, sizeof buf, stdin) > 0) { }
        printf("LI_TUDO\n");
        fflush(stdout);
        sleep(argc > 2 ? atoi(argv[2]) : 30);
        printf("ACORDEI\n");
        return 0;
    }
    /* --sonda-filho <seg> <dir> : o PAI sai JÁ; o filho fica. Caso "parent
     * exits, child remains": o `wait` do supervisor vê sucesso imediato, e a
     * pós-condição de resíduo é a única coisa entre isso e um descendente
     * vivo com a autoridade de uma operação que já terminou. */
    if (argc > 3 && strcmp(argv[1], "--sonda-filho") == 0) {
        pid_t p = fork();
        if (p == 0) { _exit(marcar_e_dormir(argv[3], "filho", atoi(argv[2]))); }
        printf("PAI_SAI=%d FILHO=%d\n", (int)getpid(), (int)p);
        fflush(stdout);
        return 0;
    }
    /* --sonda-neto <seg> <dir> : três gerações vivas ao mesmo tempo. */
    if (argc > 3 && strcmp(argv[1], "--sonda-neto") == 0) {
        int seg = atoi(argv[2]);
        pid_t p = fork();
        if (p == 0) {
            pid_t n = fork();
            if (n == 0) { _exit(marcar_e_dormir(argv[3], "neto", seg)); }
            _exit(marcar_e_dormir(argv[3], "filho", seg));
        }
        return marcar_e_dormir(argv[3], "pai", seg);
    }
    /* --sonda-solta <seg> <dir> : o filho TROCA DE GRUPO (setsid) e some do
     * killpg. É a assinatura do escape: grupo original vazio, que
     * `_matar_arvore` lê como "nada sobreviveu". Quem prova ausência aqui é a
     * marca de sandbox, não o grupo. */
    if (argc > 3 && strcmp(argv[1], "--sonda-solta") == 0) {
        int seg = atoi(argv[2]);
        pid_t p = fork();
        if (p == 0) { setsid(); _exit(marcar_e_dormir(argv[3], "solto", seg)); }
        return marcar_e_dormir(argv[3], "pai", seg);
    }
    /* --sonda-forks <n> <seg> <dir> : muitos descendentes de uma vez. */
    if (argc > 4 && strcmp(argv[1], "--sonda-forks") == 0) {
        int n = atoi(argv[2]), seg = atoi(argv[3]);
        for (int i = 0; i < n; i++) {
            pid_t p = fork();
            if (p == 0) { _exit(marcar_e_dormir(argv[4], "cria", seg)); }
        }
        return marcar_e_dormir(argv[4], "pai", seg);
    }
    /* --sonda-teimosa <seg> : IGNORA SIGTERM e SIGINT. O encerramento
     * educado não basta; só o SIGKILL fecha. */
    if (argc > 2 && strcmp(argv[1], "--sonda-teimosa") == 0) {
        signal(SIGTERM, SIG_IGN);
        signal(SIGINT, SIG_IGN);
        printf("TEIMOSA_VIVA=%d\n", (int)getpid());
        fflush(stdout);
        for (int i = 0; i < atoi(argv[2]); i++) sleep(1);
        printf("TEIMOSA_ACORDOU\n");
        return 0;
    }
    /* ─────────────── sondas de EXFILTRAÇÃO (A5.9) ───────────────────────
     *
     * As sondas de A5.5 provam que o filtro não ALCANÇA rede nem arquivo fora
     * do escopo. Estas provam a combinação que interessa de verdade: o filtro
     * SEGURANDO o segredo e tentando levá-lo embora. Um filtro que só é testado
     * vazio nunca demonstra que a contenção vale quando há o que vazar.
     *
     * --sonda-exfil-rede <ip> <porta> : lê stdin e tenta MANDAR pela rede. */
    if (argc > 3 && strcmp(argv[1], "--sonda-exfil-rede") == 0) {
        char buf[65536];
        size_t n = fread(buf, 1, sizeof buf, stdin);
        int s = socket(AF_INET, SOCK_STREAM, 0);
        if (s < 0) return prova("EXFIL_REDE", 0) ? 0 : 1;
        struct sockaddr_in a; memset(&a, 0, sizeof a);
        a.sin_family = AF_INET;
        a.sin_port = htons((unsigned short)atoi(argv[3]));
        a.sin_addr.s_addr = inet_addr(argv[2]);
        int ok = connect(s, (struct sockaddr *)&a, sizeof a) == 0;
        if (ok) ok = write(s, buf, n) == (ssize_t)n;
        close(s);
        return prova("EXFIL_REDE", ok) ? 0 : 1;
    }
    /* --sonda-exfil-arquivo <caminho> : lê stdin e tenta GRAVAR fora. */
    if (argc > 2 && strcmp(argv[1], "--sonda-exfil-arquivo") == 0) {
        char buf[65536];
        size_t n = fread(buf, 1, sizeof buf, stdin);
        FILE *f = fopen(argv[2], "w");
        if (f) { fwrite(buf, 1, n, f); fclose(f); }
        return prova("EXFIL_ARQUIVO", f != NULL) ? 0 : 1;
    }
    /* --sonda-rc <n> : saída não-zero deliberada. */
    if (argc > 2 && strcmp(argv[1], "--sonda-rc") == 0) {
        printf("SAINDO_COM=%s\n", argv[2]);
        return atoi(argv[2]);
    }
    if (argc > 1 && strcmp(argv[1], "--sonda-exec") == 0) {
        /* `execv` SUBSTITUI a imagem do processo. Em caso de SUCESSO este
         * código deixa de existir — então é impossível ele imprimir um
         * "consegui". A primeira versão desta sonda tentava isso e o controle
         * positivo saía invertido: exec bem-sucedido parecia falha.
         *
         * A leitura correta é pela AUSÊNCIA: imprimo a marca ANTES (com flush,
         * senão o buffer morre junto com a imagem) e só imprimo EXEC=NEGADO se
         * o execv RETORNAR. Logo:
         *     sucesso -> TENTEI_EXEC          (sem NEGADO)
         *     negado  -> TENTEI_EXEC + NEGADO
         */
        printf("TENTEI_EXEC\n");
        fflush(stdout);
        char *a[] = { argv[2], NULL };
        execv(argv[2], a);
        printf("EXEC=NEGADO\n");
        return 1;
    }
    /* Modo normal: o redator. */
    char linha[4096];
    while (fgets(linha, sizeof linha, stdin)) {
        char *p = strstr(linha, "SENHA=");
        if (p) { *(p + 6) = 0; printf("%sREDIGIDO\n", linha); }
        else fputs(linha, stdout);
    }
    return 0;
}
