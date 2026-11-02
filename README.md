# Publicação automática no X

Este projeto gera um post de texto por dia com base em RSS públicos e publica na conta do X autorizada pelo dono do App. A geração usa a API da OpenAI; a publicação usa a API oficial do X com OAuth 1.0a de usuário.

## Configuração no GitHub

1. No X Developer Console, configure o App com permissão **Read and write** e gere as credenciais OAuth 1.0a da conta que vai publicar.
2. Em **Settings → Secrets and variables → Actions**, cadastre `OPENAI_API_KEY`, `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN` e `X_ACCESS_TOKEN_SECRET`.
3. Confira se o workflow pode gravar commits na branch padrão. Ele usa `contents: write` para manter a fila e o histórico em `.github/x-state/`.
4. Na aba **Actions**, rode manualmente **X automatico → generate** para testar a geração. O modo **publish** envia de verdade qualquer post da fila cujo horário já passou.

O workflow tenta gerar às 07:17 e 08:17 e publicar às 09:17, 11:17 e 13:17, no fuso `America/Sao_Paulo`. Os horários extras servem para recuperar atrasos do agendamento do GitHub. O publicador registra o estado `publishing` no repositório antes da chamada ao X. Se a resposta for incerta, o post fica `uncertain` e exige conferência manual.

**Atenção em repositórios públicos:** a fila versionada contém os textos gerados antes de serem publicados. Para manter os rascunhos privados, use um repositório privado.

Os arquivos `.env`, `.post-queue/` e `.content-radar/` são locais e não entram no Git. A campanha antiga de 300 posts não é importada porque seus horários já passaram.
