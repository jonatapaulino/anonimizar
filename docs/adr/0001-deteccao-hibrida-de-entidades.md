# ADR-0001: Detecção híbrida de entidades (NER jurídico + regras determinísticas)

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

A Camada de Anonimização precisa detectar entidades sensíveis em documentos
jurídicos em português: nomes, papéis processuais, identificadores (CPF, RG,
endereços, nº de processo CNJ) e referências indiretas. Metas: F1 ≥ 0,85 e
reidentificação adversarial ≤ 5%.

A literatura citada pela proposta (Lison et al., 2021; Pilán et al./TAB, 2022)
estabelece que mascaramento puramente lexical é insuficiente e que sistemas
híbridos superam abordagens únicas.

## Opções consideradas

| Opção | Régua | Avaliação |
|-------|-------|-----------|
| Só regex/dicionário | ✅ | Precisão alta em IDs estruturados; falha em identificadores indiretos e nomes fora de lista — insuficiente sozinha |
| ML clássico (CRF/LSTM-CRF, baseline LeNER-Br 2018) | ✅ | Contexto fraco; F1 inferior a transformers |
| **BERT fine-tunado PT-BR jurídico** | ✅ | Melhor opção madura; F1 0,953 reportado (corpus STF) |
| GLiNER (zero-shot) | ❌ nov/2023 | Cortado pela régua (~23 meses) |
| LLM / Sabiá-2/3 | ❌ 2024–25 | Régua + soberania de dados |

Backbones verificados (datas reais do Hugging Face):

| Modelo | Data | Uso |
|--------|------|-----|
| `neuralmind/bert-base/large-portuguese-cased` (BERTimbau) | out/2020 | Backbone-base, SOTA PT NER |
| `dominguesm/legal-bert-ner-base-cased-ptbr` | out/2022 | Fine-tune em ~1M docs do STF (BR) — backbone de referência |
| `pierreguillou/ner-bert-*-pt-lenerbr` | dez/2021 | Detectores auxiliares, esquema LeNER-Br |
| `PORTULAN/albertina-ptbr-base` (DeBERTa-v2) | mai/2023 | Alternativa moderna — PortuLex LeNER 89,26 > BERTimbau 88,34; candidato p/ comparação no fine-tune |
| `FacebookAI/xlm-roberta-base` | nov/2019 | Alternativa multilíngue madura (fallback) |
| `rufimelo/Legal-BERTimbau-*` | 2023, no fio | PT de Portugal — jurisdição incorreta |

## Decisão

**Detecção em ensemble com três vias, fundidas por reconciliação de spans:**

1. **NER neural**: BERT-base adaptado ao domínio jurídico brasileiro
   (backbone `dominguesm` ou fine-tune próprio sobre BERTimbau;
   `albertina-ptbr-base` avaliado como comparador no fine-tune), ajustado no
   corpus sintético da Etapa 3 com tagset estendido do projeto.
2. **Regras determinísticas**: regex + validadores de dígito para CPF, nº CNJ,
   OAB, datas — precisão ~100% onde o formato é normativo.
3. **Gazetteers**: listas controladas (comarcas, tribunais, órgãos) para
   recall garantido em entidades conhecidas.

**Classificador de papéis processuais** separado do NER: papel é atributo
contextual (posição na peça, marcadores discursivos), não lexical — regras +
features sobre pessoas detectadas.

## Consequências

- **Positivas**: precisão de regras onde o formato é fixo + recall neural onde
  é contextual; cada via auditável separadamente; esquema alinhado ao TAB.
- **Custo**: nenhum modelo pronto cobre o tagset do projeto — fine-tune no
  corpus da Etapa 3 é obrigatório (já previsto na proposta).
- **Técnica**: limite de 512 tokens do BERT exige janelamento com overlap e
  reconciliação de entidades cortadas — requisito de entrada do pipeline.
- Ordem de precedência na fusão de spans: regra determinística > NER neural >
  gazetteer (a definir na especificação de merge).
