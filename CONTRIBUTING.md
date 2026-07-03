# Contribuindo — Sentinela HL

Repositório proprietário, equipe pequena. Estas convenções existem para que a
organização do projeto não fique só "na cabeça" de quem começou.

## Git Flow

Duas branches permanentes:

```
main      → sempre estável. Só recebe merge de develop (ou hotfix).
develop   → desenvolvimento diário. Base para as feature branches.
```

Nunca commite direto na `main`. Trabalho novo sai de `develop`:

```bash
git checkout develop
git checkout -b feat/112-1-workflow-n8n
# ... trabalho ...
git push -u origin feat/112-1-workflow-n8n
# abre PR para develop
```

Prefixos de branch: `feat/`, `fix/`, `docs/`, `refactor/`, `chore/`.

## Commits

Padrão Conventional Commits — facilita changelog e releases:

```
feat: adiciona filtro 3 (independência da fonte)
fix: corrige parsing de resposta do LLM com cercas ```json
docs: atualiza ARCHITECTURE com decisão do OpenRouter
refactor: extrai política para DecisionEngine
chore: bump de dependências
```

Escopo opcional: `feat(113): ...`. Mensagem no imperativo, em minúsculas.

## Antes de abrir um PR

```bash
uv run pytest sentinela/filters/tests/     # tudo verde
```

Um PR deve: passar nos testes, manter o contrato (`core/models.py`) intacto ou
migrar o schema junto, e respeitar os princípios abaixo.

## Princípios que um PR não pode violar

- **Contrato único** — `core/models.py` espelha o schema SQL. Mudou o model?
  Tem migration nova (`0XX_...sql`) junto. Nunca duas fontes de verdade.
- **n8n não pensa** — nenhuma regra de negócio em nós de n8n. Lógica em Python.
- **Sem acoplar a provedor** — nada importa Claude/OpenAI direto; só `LLMClient`.
- **Política no DecisionEngine** — regra de decisão nunca vaza para os filtros.
- **Sem regra no OpenRouterClient** — o client só transporta texto.
- **Migrations divididas** — nunca uma migration monolítica.
- **YAGNI** — sem Domains/Services/Repository/Factory/DI sem necessidade real.

## Prompts

O prompt é artefato versionado em `sentinela/prompts/`. Não edite `filter_v1.md`
para mudar comportamento — crie `filter_v2.md` e compare com o benchmark:

```bash
uv run python benchmarks/run_bench.py
```

Assim a versão que produziu cada classificação fica rastreável (`prompt_version`).

## Migrations

```bash
supabase migration new descricao_curta
# edite o arquivo gerado em supabase/migrations/
supabase db reset      # em dev: recria o banco aplicando tudo em ordem
```

Segredos nunca entram no repositório — só `.env.example`. O `.env` real está no
`.gitignore`.

## Releases

Versionamento semântico. O primeiro release sai quando a Milestone 2 permitir um
fluxo ponta a ponta:

```
v0.1.0-alpha   → primeiro fluxo completo (após o Documento 112)
```

Fluxo de release:

```bash
git checkout main
git merge --no-ff develop
git tag -a v0.1.0-alpha -m "primeiro fluxo ponta a ponta"
git push origin main --tags
```

Tags de pré-lançamento: `-alpha`, `-beta`, `-rc.1`.
