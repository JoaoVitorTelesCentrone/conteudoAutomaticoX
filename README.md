# Publicação automática no X

O projeto publica **15 posts por dia** na conta X autorizada, nos horários de **08:00 a 22:00**, um por hora, no fuso `America/Sao_Paulo`. A campanha inicial usa os **300 textos existentes** de `x-primeiro-mes-300.json`, agendados de **03/11/2026 a 22/11/2026**. Depois, o radar gera e revisa 15 textos novos para cada dia seguinte com a API da OpenAI.

## Configuração

1. No X Developer Console, deixe o App com permissão **Read and write** e gere as credenciais OAuth 1.0a da conta `@Joaocentrone1`.
2. Em **Settings → Secrets and variables → Actions**, configure `OPENAI_API_KEY`, `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN` e `X_ACCESS_TOKEN_SECRET`.
3. O workflow precisa de permissão para gravar commits na branch padrão. Ele salva a fila e o histórico em `.github/x-state/` usando `contents: write`.

O workflow tenta gerar posts às **06:17** e **07:17** para o dia seguinte. Enquanto a campanha de 300 posts estiver preenchida, a geração não chama a OpenAI. A primeira geração de um dia novo está prevista para **22/11/2026**, preparando **23/11/2026**.

A publicação é verificada às **:17** e **:47** de cada hora entre 08h e 22h. A segunda verificação recupera atrasos sem duplicar posts. O GitHub Actions pode atrasar ou perder execuções agendadas; por isso, o resultado real deve ser conferido em **Actions** e no campo `status` de `.github/x-state/queue.json`. `published` e `x_post_id` confirmam o envio. Um job verde que imprime “Nenhum post do X pendente para agora” não publicou nada.

Antes de chamar a API do X, o publicador salva `publishing` no GitHub. Se a chamada der resultado incerto, o post fica `uncertain` e exige conferência no X antes de qualquer tentativa manual. Posts com mais de seis horas de atraso expiram, para evitar publicação fora de contexto.

Para rodar manualmente, abra **Actions → X automatico → Run workflow**. `generate` completa os 15 horários de amanhã; `publish` envia um post vencido da fila, se houver. **`publish` envia de verdade.**

No Windows, instale `requirements.txt` antes de executar os scripts localmente; ele fornece os dados IANA de fuso horário. O workflow faz a instalação automaticamente.

**Repositório público:** `.github/x-state/queue.json` contém os textos antes da publicação. Para manter os rascunhos privados, use um repositório privado. Os arquivos `.env`, `.post-queue/` e `.content-radar/` são locais e não entram no Git.
