"""Serviço de consulta e validação de CEP.

Usa a API pública viaCEP para buscar dados de endereço a partir do CEP.
https://viacep.com.br/
"""

from typing import Any, Dict, Optional
import httpx


class CEPService:
    """Serviço para consultar dados de endereço via CEP."""

    VIA_CEP_URL = "https://viacep.com.br/ws/{cep}/json"

    @staticmethod
    def lookup(cep: str) -> Dict[str, Any]:
        """
        Busca dados de endereço a partir do CEP.

        Args:
            cep: CEP com 8 dígitos (sem formatação)

        Returns:
            Dicionário com dados do endereço ou erro.
            Exemplo de sucesso:
            {
                "success": True,
                "logradouro": "Rua da Paz",
                "bairro": "Centro",
                "cidade": "São Paulo",
                "estado": "SP",
            }
            Exemplo de erro:
            {
                "success": False,
                "error": "CEP não encontrado",
            }
        """
        # Validar CEP
        digits = cep.replace("-", "").strip()
        if len(digits) != 8 or not digits.isdigit():
            return {
                "success": False,
                "error": "CEP inválido. Informe 8 dígitos.",
            }

        try:
            url = CEPService.VIA_CEP_URL.format(cep=digits)
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            # viaCEP retorna {"erro": True} quando não encontra
            if data.get("erro") is True:
                return {
                    "success": False,
                    "error": "CEP não encontrado.",
                }

            # Validar campos retornados
            if not all(data.get(key) for key in ["logradouro", "bairro", "localidade", "uf"]):
                return {
                    "success": False,
                    "error": "Dados de CEP incompletos.",
                }

            return {
                "success": True,
                "logradouro": data.get("logradouro") or "",
                "bairro": data.get("bairro") or "",
                "cidade": data.get("localidade") or "",
                "estado": (data.get("uf") or "").upper(),
                "complemento": data.get("complemento") or "",
            }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Timeout ao consultar CEP. Tente novamente.",
            }
        except httpx.HTTPError as exc:
            return {
                "success": False,
                "error": f"Erro ao consultar CEP: {str(exc)}",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": f"Erro inesperado: {str(exc)}",
            }


def get_cep_service() -> CEPService:
    return CEPService()
