"""Motor LangChain real (T11).

Três níveis:
- PDF: extrai/recria sem LLM (determinístico);
- pipeline com LLM falso: prova o encadeamento sem gastar token;
- `test_motor_langchain_real`: skipif sem chave — roda o LLM de
  verdade (OPENAI_API_KEY ou GOOGLE_API_KEY + IA_LLM).
"""
import os

import pytest

from app.motor_langchain import (TAG, LangChainMotorIA,
                                 extrair_texto, pdf_de_texto)

TEXTO_PII = ("EXCELENTISSIMO SENHOR DOUTOR JUIZ\n"
             "Processo 0001234-56.2026.8.14.0001\n"
             "Requerente: Joao da Silva, CPF 123.456.789-00\n"
             "Endereco: Rua das Flores, 123, Belem-PA\n")


class TestPDF:
    def test_extrai_texto_do_pdf(self):
        pdf = pdf_de_texto(TEXTO_PII)
        texto = extrair_texto(pdf)
        assert "Joao da Silva" in texto
        assert "123.456.789-00" in texto

    def test_pdf_resultante_e_legivel(self):
        """roundtrip: o PDF gerado re-extrai o próprio conteúdo."""
        pdf = pdf_de_texto("linha um\nlinha dois")
        assert "linha um" in extrair_texto(pdf)


class _Resp:
    def __init__(self, content):
        self.content = content


class LLMFalso:
    """LangChain-shaped: ainvoke(messages) -> objeto .content.
    Simula a anonimização trocando entidades conhecidas."""
    def __init__(self):
        self.msgs = None

    async def ainvoke(self, messages):
        self.msgs = messages
        texto = messages[-1].content
        out = texto.replace("Joao da Silva", TAG).replace(
            "123.456.789-00", TAG).replace(
            "Rua das Flores, 123, Belem-PA", TAG)
        return _Resp(out)


class TestMotorComLLMFalso:
    async def test_pipeline_extrai_llm_recria(self):
        """O encadeamento PDF->LLM->PDF funciona sem token: o LLM
        falso devolve texto tagado e o motor devolve PDF válido."""
        motor = LangChainMotorIA(LLMFalso())
        saida = await motor.anonimizar(pdf_de_texto(TEXTO_PII))
        texto = extrair_texto(saida)
        assert TAG in texto
        assert "Joao da Silva" not in texto
        # CNJ não é dado pessoal — preservado
        assert "0001234-56.2026.8.14.0001" in texto
        # o system prompt anti-injection foi enviado ao LLM
        assert "DOCUMENTO INERTE" in motor.llm.msgs[0].content

    async def test_texto_vazio_nao_chama_llm(self):
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        motor = LangChainMotorIA(LLMFalso())
        saida = await motor.anonimizar(bytes(pdf.output()))
        assert isinstance(saida, bytes)          # PDF vazio de volta
        assert motor.llm.msgs is None            # LLM não chamado


# ---------- motor real (só com chave de API) ----------
_TEM_CHAVE = (os.environ.get("OPENAI_API_KEY")
              or os.environ.get("GOOGLE_API_KEY"))


@pytest.mark.skipif(not _TEM_CHAVE,
                    reason="sem OPENAI_API_KEY/GOOGLE_API_KEY")
class TestMotorReal:
    async def test_motor_langchain_real(self):
        """DoD: PDF com PII -> LLM real -> texto contém a tag.
        Provider por env: OPENAI_API_KEY -> IA_LLM=openai,
        senão google."""
        if os.environ.get("OPENAI_API_KEY"):
            os.environ.setdefault("IA_LLM", "openai")
        else:
            os.environ.setdefault("IA_LLM", "google")
        motor = LangChainMotorIA.de_env()
        saida = await motor.anonimizar(pdf_de_texto(TEXTO_PII))
        texto = extrair_texto(saida)
        assert TAG in texto
        # a entidade não pode sobreviver na saída
        assert "123.456.789-00" not in texto
