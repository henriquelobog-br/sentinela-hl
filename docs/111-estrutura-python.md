# Documento 111 — Estrutura Python

Estrutura plana por tecnologia. **Contrato primeiro**: o dado que flui entre
módulos (Pydantic) é o contrato central; as `interface.py` (Protocols) são
consequência.

## Árvore
```
python/
├── pyproject.toml          # uv; deps: pydantic, pydantic-settings
├── shared/
│   ├── models.py           # ★ contrato central — ancorado no schema 101
│   ├── config.py           # env (defaults batem com o Doc 110)
│   └── logger.py           # log estruturado JSON, sem dep externa
├── collector/{interface,rss,api}.py
├── parser/{interface,normalizer}.py
├── filters/{interface,filter1,filter2,filter4}.py
├── classifier/{interface,extractor}.py
├── writer/{interface,bulletin}.py
└── prompts/
```

## Decisões
- **Protocol** (não ABC): structural, sem herança, testável.
- **Pydantic v2**: validação na fronteira (RSS/API/Claude/JSON).
- **models = SQL**: os 9 enums espelham `public.*` do Doc 101 (validado por teste cruzado).
- **Stubs** levantam `NotImplementedError` — a lógica é o Documento 113.

## Contratos que fluem no pipeline
`RawItem` → `Claim` → `Classification` (por filtro) → `FilterReport` (veredito)
→ `Event` → `Bulletin`.

A decisão de roteamento (`pass`/`escalate`/`reject`) em `FilterReport` tem o
FORMATO definido aqui; a LÓGICA que a produz é o Documento 113.

## Rodar
```
cd python
uv sync                      # ou: pip install -e .
python -c "import shared.models"   # sanity
```

## Próximo
Documento 113 — implementar Filtros 1, 2 e 4 (standalone, contra casos-teste
incluindo o Namib), preenchendo os stubs sem tocar nos contratos.
