# Guide de Dépannage - Bot Telegram Uploader

## Problème : "Une erreur est survenue lors de la récupération des canaux"

### Symptômes
- Le bot fonctionne en local mais pas en production
- Erreur : "❌ Une erreur est survenue lors de la récupération des canaux"
- Le bot ne peut pas récupérer la liste des canaux

### Causes possibles
1. **Tables de base de données manquantes** (le plus probable)
2. **Permissions insuffisantes** sur le fichier de base de données
3. **Variables d'environnement** non configurées
4. **Fichiers de session** manquants ou corrompus

## Solutions

### 1. Diagnostic automatique
Exécutez le script de diagnostic pour identifier le problème :

```bash
cd "RENAN/BOT UPLOADER"
python diagnostic.py
```

### 2. Initialisation de la base de données
Si des tables manquent, exécutez le script d'initialisation :

```bash
cd "RENAN/BOT UPLOADER"
python init_database.py
```

### 3. Vérification manuelle de la base de données

#### Vérifier que toutes les tables existent :
```sql
.tables
```

Vous devriez voir :
- channels
- channel_members
- files
- posts
- users
- user_settings

#### Vérifier les permissions :
```bash
ls -la bot.db
```

Le fichier doit être accessible en lecture/écriture.

### 4. Configuration des variables d'environnement

Créez un fichier `.env` dans le répertoire du bot :

```env
# API Telegram
API_ID=votre_api_id
API_HASH=votre_api_hash
BOT_TOKEN=votre_bot_token

# Configuration de la base de données
DB_PATH=bot.db

# Dossiers
DOWNLOAD_FOLDER=downloads/
TEMP_FOLDER=temp/

# Administrateurs (optionnel)
ADMIN_IDS=[123456789,987654321]

# Canal par défaut (optionnel)
DEFAULT_CHANNEL=https://t.me/sheweeb
```

### 5. Vérification des dossiers requis

Assurez-vous que ces dossiers existent :
```bash
mkdir -p downloads temp thumbnails logs backups
```

### 6. Redémarrage du bot

Après avoir appliqué les corrections :

```bash
# Arrêter le bot
sudo systemctl stop bot

# Redémarrer le bot
sudo systemctl start bot

# Vérifier le statut
sudo systemctl status bot

# Voir les logs
journalctl -u bot -f
```

## Problèmes courants et solutions

### Erreur "no such table: files"
**Solution :** Exécutez `python init_database.py`

### Erreur "database is locked"
**Solution :** 
1. Arrêtez le bot
2. Supprimez les fichiers temporaires : `rm -f bot.db-wal bot.db-shm`
3. Redémarrez le bot

### Erreur "permission denied"
**Solution :**
```bash
sudo chown -R $USER:$USER .
chmod 644 bot.db
chmod 755 downloads temp thumbnails logs
```

### Erreur "Event loop is closed"
**Solution :** Redémarrez le bot, cette erreur est normale lors de l'arrêt

## Logs utiles

### Voir les logs en temps réel :
```bash
tail -f logs/uploader_bot.log
```

### Voir les logs système :
```bash
journalctl -u bot -f
```

### Voir les erreurs récentes :
```bash
journalctl -u bot --since "1 hour ago" | grep ERROR
```

## Test de fonctionnement

Après avoir appliqué les corrections, testez le bot :

1. Envoyez `/start` au bot
2. Vérifiez que le menu principal s'affiche
3. Testez la création d'une publication
4. Vérifiez que les canaux s'affichent correctement

## Support

Si le problème persiste :

1. Exécutez `python diagnostic.py` et partagez la sortie
2. Vérifiez les logs : `tail -100 logs/uploader_bot.log`
3. Vérifiez les logs système : `journalctl -u bot --no-pager`

## Prévention

Pour éviter ces problèmes à l'avenir :

1. **Toujours initialiser la base de données** avant le premier démarrage
2. **Vérifier les permissions** sur les fichiers et dossiers
3. **Configurer correctement** les variables d'environnement
4. **Faire des sauvegardes** régulières de la base de données
5. **Monitorer les logs** pour détecter les problèmes rapidement
