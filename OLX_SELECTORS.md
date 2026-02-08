# Seletores OLX - Análise da Página Interna

## URL do Anúncio
Padrão: `https://mg.olx.com.br/regiao-de-montes-claros-e-diamantina/autos-e-pecas/carros-vans-e-utilitarios/[modelo]-[ano]-[ID]`

Exemplo: `https://mg.olx.com.br/regiao-de-montes-claros-e-diamantina/autos-e-pecas/carros-vans-e-utilitarios/fiat-punto-sporting-1-8-flex-8v-16v-5p-2014-1475512233`

## Dados Extraídos

### 1. Título
**Seletor**: `span.typo-title-medium.ad__sc-1l883pa-2.bdcWAn` ou `span[class*="typo-title-medium"][class*="ad__sc-1l883pa-2"]`

**Exemplo**: "Fiat Punto Sporting 1.8 Flex 8v/16v 5P 2014"

**Alternativa**: Meta tag `<meta property="og:title" content="...">`

### 2. Preço
**Seletor**: `#price-box-container span.typo-title-large` ou `span.typo-title-large` dentro de `#price-box-container`

**Exemplo**: "R$ 46.500"

**Formato**: Texto com "R$ " e pontos como separador de milhar

**Processamento**: Remover "R$ ", pontos e converter para float

### 3. Ano
**Seletor**: Após `<span class="typo-overline mb-0-5 text-neutral-120">Ano</span>`, buscar o link `<a class="olx-link olx-link--small olx-link--grey ad__sc-2h9gkk-3 lkkHCr">`

**Ou**: Buscar por `span:has-text("Ano") + div a` ou `a[href*="/2014/"]` e extrair do texto ou href

**Exemplo**: "2014"

**Alternativa**: Extrair do título ou URL (último número antes do ID)

### 4. Quilometragem
**Seletor**: Após `<span class="typo-overline mb-0-5 text-neutral-120">Quilometragem</span>`, buscar o próximo `<span>` com número

**Ou**: `span:has-text("Quilometragem") + div span` (sem classe específica, apenas número)

**Exemplo**: "135558" (sem "km" no texto)

**Processamento**: Converter string numérica para int

### 5. Cidade
**Seletor**: `span.typo-body-small.font-semibold.text-neutral-110` que contém "Montes Claros"

**Ou**: Buscar por padrão "Cidade, Estado" dentro de elementos de localização

**Exemplo**: "Montes Claros, MG"

**Processamento**: Separar cidade e estado (split por vírgula)

### 6. Foto Principal
**Seletor**: Meta tag `<meta property="og:image" content="...">`

**Ou**: Primeira imagem na galeria: `img[alt*="Fiat"]` ou `img[src*="img.olx.com.br/images"]`

**Exemplo**: `https://img.olx.com.br/images/83/839611378602021.jpg`

**Alternativa**: `img[data-display="single"]` ou primeira imagem com `fetchpriority="high"`

### 7. Descrição
**Seletor**: `div[data-section="description"] span.typo-body-medium`

**Ou**: `div.ad__sc-2mjlki-0.iAOKgI span.typo-body-medium`

**Exemplo**: "Punto Sporting 2014 ! Carro top sem detalhes nenhum..."

**Nota**: Pode conter telefone oculto como "(38)... ver número" - remover isso

## Estrutura de Dados Esperada

```json
{
  "url": "https://mg.olx.com.br/.../fiat-punto-sporting-1-8-flex-8v-16v-5p-2014-1475512233",
  "title": "Fiat Punto Sporting 1.8 Flex 8v/16v 5P 2014",
  "price": 46500.0,
  "price_display": "R$ 46.500",
  "year": 2014,
  "km": 135558,
  "city": "Montes Claros",
  "state": "MG",
  "description": "Punto Sporting 2014 ! Carro top sem detalhes nenhum...",
  "main_photo_url": "https://img.olx.com.br/images/83/839611378602021.jpg",
  "scanned_at": "2026-02-06 10:16:01"
}
```

## Seletores Alternativos (Fallback)

### Título
1. `span.typo-title-medium.ad__sc-1l883pa-2.bdcWAn`
2. `meta[property="og:title"]`
3. `title` tag (remover " - [ID] | OLX")

### Preço
1. `#price-box-container span.typo-title-large`
2. Buscar regex `R\$\s*([\d\.]+)` no texto da página

### Ano
1. Link após "Ano" label
2. Extrair do título (último número de 4 dígitos)
3. Extrair da URL (número antes do ID final)

### Quilometragem
1. Span após "Quilometragem" label
2. Buscar regex `(\d+)\s*km` no texto (case insensitive)

### Cidade
1. `span.typo-body-small.font-semibold.text-neutral-110` contendo cidade
2. Buscar padrão de endereço na seção de localização

### Foto
1. `meta[property="og:image"]`
2. Primeira `img[src*="img.olx.com.br/images"]`
3. `img[fetchpriority="high"]`

### Descrição
1. `div[data-section="description"] span.typo-body-medium`
2. `meta[property="og:description"]`
3. `meta[name="description"]`

## Observações Importantes

1. **Normalização de URL**: Converter `mg.olx.com.br` para `www.olx.com.br` se necessário
2. **Telefone**: Descrição pode conter "(38)... ver número" - remover antes de salvar
3. **Quilometragem**: Pode não ter "km" no texto, apenas número
4. **Preço**: Sempre tem formato "R$ XX.XXX" (pontos como separador de milhar)
5. **Ano**: Sempre 4 dígitos (ex: 2014)
6. **Cidade/Estado**: Formato "Cidade, Estado" (separar por vírgula)

## Estrutura da Página

- **Container principal**: `div#adview` ou `div.ad__sc-1bw7mho-0`
- **Seção de informações**: Containers com classe `ad__sc-2h9gkk-0` (características)
- **Preço**: `div#price-box-container`
- **Descrição**: `div[data-section="description"]`
- **Localização**: Seção com "Jardim Palmeiras" e "Montes Claros, MG"
