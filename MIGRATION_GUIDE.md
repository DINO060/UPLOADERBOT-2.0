# 🌍 Guide de Migration vers l'Internationalisation (i18n)

Ce guide vous explique comment migrer progressivement votre bot Telegram vers un système multilingue sans réécrire tout le code.

## 📋 Vue d'ensemble

Le système d'internationalisation permet de :
- ✅ Supporter plusieurs langues (FR/EN)
- ✅ Changer de langue en temps réel
- ✅ Migrer progressivement sans tout réécrire
- ✅ Gérer les variables et pluriels

## 🚀 Installation

Le système est déjà installé avec :
- `i18n.py` - Module principal
- `locales/en.json` - Traductions anglaises
- `locales/fr.json` - Traductions françaises
- Handlers `/language` - Changement de langue

## 📝 Comment utiliser

### 1. Import du module

```python
from i18n import get_user_lang, t, tn
```

### 2. Récupérer la langue utilisateur

```python
user = update.effective_user
lang = get_user_lang(user.id, user.language_code)
```

### 3. Utiliser les traductions

```python
# Texte simple
await update.message.reply_text(t(lang, "start.welcome"))

# Avec variables
await update.message.reply_text(t(lang, "success.channel_added", username="mon_canal", tag="news"))

# Avec pluriels
await update.message.reply_text(tn(lang, "post.scheduled", count=1))  # "1 publication planifiée"
await update.message.reply_text(tn(lang, "post.scheduled", count=5))  # "5 publications planifiées"
```

## 🔄 Migration Progressive

### Étape 1 : Identifier les messages

Cherchez les chaînes de caractères dans votre code :
```python
# AVANT
await update.message.reply_text("✅ Canal ajouté avec succès!")

# APRÈS
await update.message.reply_text(t(lang, "success.channel_added"))
```

### Étape 2 : Ajouter les clés

Ajoutez les nouvelles clés dans `locales/en.json` et `locales/fr.json` :

```json
// locales/en.json
{
  "success.channel_added": "✅ Channel added successfully!"
}

// locales/fr.json
{
  "success.channel_added": "✅ Canal ajouté avec succès!"
}
```

### Étape 3 : Remplacer progressivement

Commencez par les messages les plus utilisés :
1. Messages d'accueil (`/start`)
2. Messages d'erreur
3. Messages de succès
4. Menus et boutons

## 📚 Exemples de Migration

### Exemple 1 : Message simple

```python
# AVANT
async def handle_error(update, context):
    await update.message.reply_text("Une erreur est survenue. Veuillez réessayer.")

# APRÈS
async def handle_error(update, context):
    user = update.effective_user
    lang = get_user_lang(user.id, user.language_code)
    await update.message.reply_text(t(lang, "errors.generic"))
```

### Exemple 2 : Message avec variables

```python
# AVANT
await update.message.reply_text(f"✅ Canal ajouté : @{username}")

# APRÈS
await update.message.reply_text(t(lang, "success.channel_added", username=username))
```

### Exemple 3 : Pluriels

```python
# AVANT
if count == 1:
    message = "1 publication planifiée"
else:
    message = f"{count} publications planifiées"

# APRÈS
message = tn(lang, "post.scheduled", count=count)
```

## 🎯 Commandes Disponibles

### `/language`
Change la langue du bot avec des boutons interactifs.

### `/help`
Affiche l'aide dans la langue sélectionnée.

## 📁 Structure des Fichiers

```
mon_bot_telegram/
├── i18n.py                 # Module principal
├── locales/
│   ├── en.json            # Traductions anglaises
│   └── fr.json            # Traductions françaises
└── MIGRATION_GUIDE.md     # Ce guide
```

## 🔧 Ajouter une Nouvelle Langue

1. Créez `locales/es.json` (exemple pour l'espagnol)
2. Ajoutez la langue dans `i18n.py` :

```python
SUPPORTED = {
    "en": {"name": "English", "flag": "🇬🇧"},
    "fr": {"name": "Français", "flag": "🇫🇷"},
    "es": {"name": "Español", "flag": "🇪🇸"},  # Nouvelle langue
}
```

## 🚨 Bonnes Pratiques

### ✅ À faire
- Utilisez des clés descriptives : `success.channel_added`
- Groupez les clés par fonction : `errors.*`, `success.*`, `menu.*`
- Testez les deux langues après chaque ajout

### ❌ À éviter
- Ne pas utiliser de clés trop génériques : `"message"`
- Ne pas oublier d'ajouter les traductions dans les deux fichiers
- Ne pas utiliser de variables non définies

## 🧪 Test

1. Démarrez le bot
2. Envoyez `/language`
3. Choisissez 🇫🇷 ou 🇬🇧
4. Testez `/start` - le message doit changer de langue
5. La préférence est sauvegardée en base de données

## 📈 Progression

Pour suivre votre progression de migration :

1. **Phase 1** : Messages principaux (start, help, errors)
2. **Phase 2** : Messages de succès et confirmations
3. **Phase 3** : Menus et boutons
4. **Phase 4** : Messages spécialisés et avancés

## 🆘 Support

Si vous rencontrez des problèmes :
1. Vérifiez que les clés existent dans les deux fichiers JSON
2. Vérifiez la syntaxe JSON (pas de virgule en trop)
3. Redémarrez le bot après modification des fichiers de traduction

---

**Note** : Ce système permet une migration progressive. Vous pouvez continuer à utiliser des chaînes en dur pendant la migration, puis les remplacer une par une.
