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
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

static int prova(const char *rot, int ok) {
    printf("%s=%s\n", rot, ok ? "ALCANCEI" : "NEGADO");
    return ok;
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
