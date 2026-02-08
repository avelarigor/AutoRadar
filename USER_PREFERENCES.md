# Configuração – user_preferences.json

**Created by Igor Avelar — avelar.igor@gmail.com**

Todas as preferências do AutoRadar ficam em **user_preferences.json** na pasta do projeto. Edite esse arquivo com um editor de texto para alterar.

## Campos principais

| Campo | Significado | Exemplo |
|-------|-------------|---------|
| **city** | Cidade para buscar anúncios | `"Montes Claros"` |
| **state** | Estado (UF) | `"MG"` |
| **price_min** | Preço mínimo (R$). Use **0** = sem limite | `0` |
| **price_max** | Preço máximo (R$). Use **0** = sem limite | `0` |
| **margin_min_reais** | Margem mínima em reais para entrar no ranking (ex.: só oportunidades com ganho ≥ R$ 5.000) | `5000` |
| **run_every_minutes** | Intervalo em minutos para rodar o pipeline automaticamente (ex.: 60 = a cada 1 hora). Mín. 1, máx. 1440 (24 h) | `60` |
| **vehicle_types** | Tipos de veículo: `car`, `motorcycle`, `truck` (true/false) | `{"car": true, "motorcycle": true, "truck": true}` |

- **Preço:** `price_min` e `price_max` em **0** = escanear todos, sem filtro de preço.
- **Margem:** `margin_min_reais`: 5000 = só aparecem no ranking anúncios com margem (FIPE − preço) ≥ R$ 5.000.

Se o arquivo não existir, o app cria um com os valores padrão (Montes Claros, MG; sem limite de preço; margem mín. R$ 5.000).

## Módulos opcionais (Webmotors, Mobiauto, OLX)

O AutoRadar suporta coleta de anúncios de outras plataformas além do Facebook Marketplace:

### Webmotors
```json
"webmotors": {
  "_instructions": "Para usar a Webmotors: 1) Acesse www.webmotors.com.br no navegador, 2) Configure os filtros desejados (cidade, preço, etc.), 3) Copie o link completo da página de resultados, 4) Cole aqui em 'search_url'. Se deixar vazio, usa padrão Montes Claros/MG.",
  "enabled": true,
  "search_url": "https://www.webmotors.com.br/carros-usados/mg-montes-claros?..."
}
```

### Mobiauto
```json
"mobiauto": {
  "_instructions": "Para usar a Mobiauto: 1) Acesse www.mobiauto.com.br no navegador, 2) Configure os filtros desejados (cidade, preço, etc.), 3) Copie o link completo da página de resultados, 4) Cole aqui em 'search_url'. Se deixar vazio, usa padrão Montes Claros/MG.",
  "enabled": true,
  "search_url": "https://www.mobiauto.com.br/comprar/carros-usados/mg-montes-claros"
}
```

### OLX
```json
"olx": {
  "_instructions": "Para usar a OLX: 1) Acesse www.olx.com.br no navegador, 2) Configure os filtros desejados (cidade, preço, etc.), 3) Ordene por 'Mais recentes' (parâmetro ?sf=1 na URL), 4) Copie o link completo da página de resultados, 5) Cole aqui em 'search_url'. Se deixar vazio, usa padrão Montes Claros/MG ordenado por mais recentes. IMPORTANTE: Apenas a primeira página será coletada (~105 anúncios).",
  "enabled": true,
  "search_url": "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?sf=1"
}
```

**Notas importantes:**
- Todos os módulos são **ativos por padrão** (`enabled: true`).
- Para desabilitar um módulo, altere `enabled` para `false`.
- Se `search_url` estiver vazio, será usado o padrão (Montes Claros/MG).
- **OLX**: Apenas a primeira página é coletada (~105 anúncios). Para garantir que apareçam os mais recentes, inclua `?sf=1` na URL.
