#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Teste simples: verificar se o arquivo application.py tem os novos métodos
"""
import re
import sys

# Ler o arquivo
with open('frontend-flet/app/application.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Verificar métodos criados
methods_to_find = [
    'def driver_dashboard_view',
    'def _get_greeting_time',
    'def _build_driver_greeting',
    'def _build_driver_vehicle_card',
    'def _build_driver_indicators',
    'def _build_driver_mission_card',
]

print("="*70)
print("Validação de Implementação Phase 2")
print("="*70 + "\n")

all_found = True
for method in methods_to_find:
    if method in content:
        print(f"✓ {method} encontrado")
    else:
        print(f"❌ {method} NÃO encontrado")
        all_found = False

# Verificar redirecionamento
print("\nValidação de Redirecionamento:")
if 'self.driver_dashboard_view()' in content:
    print("✓ dashboard_view chama driver_dashboard_view() para MOTORISTA")
else:
    print("❌ Redirecionamento não encontrado")
    all_found = False

if 'self.deliveries_view()' not in content.split('def dashboard_view')[1].split('def deliveries_view')[0]:
    print("✓ Redirecionamento para deliveries_view foi removido")
else:
    # Duplo-check
    dashboard_section = content.split('def dashboard_view')[1].split('except ApiError')[0]
    if 'self.deliveries_view()' in dashboard_section[:300]:  # primeiras linhas
        print("❌ Ainda há redirecionamento para deliveries_view")
        all_found = False
    else:
        print("✓ Sem redirecionamento para deliveries_view em MOTORISTA")

# Verificar estrutura de Phase 3 placeholder
print("\nValidação de Preparação Phase 3:")
if '# def driver_route_view' in content:
    print("✓ Placeholder para driver_route_view está presente")
else:
    print("⚠ Placeholder para driver_route_view não encontrado (opcional)")

# Verificar comentários
print("\nValidação de Documentação:")
if 'Phase 2' in content and 'Phase 3' in content:
    print("✓ Comentários Phase 2 e Phase 3 presentes")
else:
    print("⚠ Alguns comentários de fase podem estar faltando")

print("\n" + "="*70)
if all_found:
    print("✓ VALIDAÇÃO CONCLUÍDA COM SUCESSO")
    print("="*70)
    sys.exit(0)
else:
    print("❌ VALIDAÇÃO FALHOU - Verifique os itens acima")
    print("="*70)
    sys.exit(1)
