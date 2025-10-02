#!/bin/bash

# Script de debug pour analyser les logs du bot
echo "=== ANALYSE DES LOGS DU BOT ==="
echo ""

echo "1. Dernières activités Send menu:"
grep -n "Send menu displayed" /root/UPLOADERBOT-2.0/logs/bot.log | tail -10

echo ""
echo "2. Callbacks send_now reçus:"
grep -n "Callback send_now reçu" /root/UPLOADERBOT-2.0/logs/bot.log | tail -5

echo ""
echo "3. Erreurs de canal:"
grep -n -A3 -B3 "Aucun canal" /root/UPLOADERBOT-2.0/logs/bot.log | tail -20

echo ""
echo "4. Messages d'erreur récents:"
grep -n "ERROR\|WARNING" /root/UPLOADERBOT-2.0/logs/bot.log | tail -10

echo ""
echo "5. État des canaux sélectionnés:"
grep -n "selected_channel\|Target channel\|Resolved channel" /root/UPLOADERBOT-2.0/logs/bot.log | tail -10

echo ""
echo "=== FIN DE L'ANALYSE ==="