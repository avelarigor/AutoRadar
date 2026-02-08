# Script de Teste OLX Mobile

## Objetivo
Testar acesso, estrutura HTML, coleta de links e extração de dados básicos da OLX versão mobile antes de implementar o módulo completo.

## Como Executar

```bash
cd c:\Projects\AutoRadar
python test_olx_scraping.py
```

## O que o script faz

1. **Teste 1: Acesso básico**
   - Acessa `m.olx.com.br` com User-Agent mobile
   - Usa o mesmo perfil Chrome do Facebook (`chrome_login_profile`)
   - Detecta bloqueios Cloudflare ou redirecionamentos para login
   - Salva HTML da página inicial em cache

2. **Teste 2: Coleta de links**
   - Coleta todos os links de anúncios da primeira página
   - Faz scroll para carregar mais conteúdo
   - Salva links em JSON e HTML atualizado

3. **Teste 3: Extração de dados**
   - Acessa até 5 anúncios da primeira página
   - Extrai: título, preço, ano, km, cidade, foto principal
   - Delay de 5s entre cada anúncio
   - Salva dados extraídos em JSON

4. **Teste 4: Paginação**
   - Testa acesso à segunda página (`?o=2`)
   - Coleta links da segunda página
   - Verifica se não há bloqueio

## Arquivos Gerados

Todos os arquivos são salvos em `test_olx_cache/`:

- `00_test_report.json` - Relatório final com lista de arquivos
- `01_homepage.html` - HTML da página inicial
- `02_links_collected.json` - Links coletados da primeira página
- `02_page_with_links.html` - HTML após scroll
- `03_extracted_data.json` - Dados extraídos dos anúncios
- `04_links_page2.json` - Links da segunda página
- `04_page2.html` - HTML da segunda página
- `test_log.txt` - Log detalhado de todas as operações

## Análise dos Resultados

1. **Verificar bloqueios**: Se aparecer `01_cloudflare_challenge.html` ou `01_login_redirect.html`, há bloqueio
2. **Analisar estrutura**: Abrir `01_homepage.html` no navegador para identificar seletores corretos
3. **Verificar links**: Conferir `02_links_collected.json` para ver quantos links foram encontrados
4. **Validar extração**: Verificar `03_extracted_data.json` para ver se os dados foram extraídos corretamente

## Logs Detalhados

Todos os logs são salvos em `test_log.txt` com timestamps e níveis:
- `INFO` - Informações gerais
- `SUCCESS` - Operações bem-sucedidas
- `WARN` - Avisos (ex.: bloqueios detectados)
- `ERROR` - Erros
- `CACHE` - Operações de cache

## Limpeza do Cache

Após análise, você pode deletar a pasta `test_olx_cache/`:

```bash
rmdir /s /q test_olx_cache
```

Ou manualmente pelo explorador de arquivos.

## Próximos Passos

Após validar os testes:
1. Identificar seletores corretos analisando os HTMLs salvos
2. Ajustar o script se necessário
3. Implementar módulo completo `collect_links_olx.py` e `scan_olx.py`
4. Integrar ao pipeline principal em `run_app.py`
