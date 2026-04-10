# SEO оптимизация — как использовать

## Что уже сделано

### 1. Мета-теги (в `<head>`)
- **title** — заголовок вкладки и в результатах поиска (до 60 символов)
- **description** — описание сайта в поиске (до 160 символов)
- **keywords** — ключевые слова (влияние ограничено, но не вредит)
- **author** — автор контента
- **canonical** — основной URL страницы (защита от дублей)

### 2. Open Graph (соцсети)
При расшаривании ссылки в Facebook, VK, Telegram и др. подтягиваются:
- заголовок
- описание
- превью-картинка

### 3. Twitter Card
Аналогично Open Graph, но для Twitter/X — крупное превью с картинкой.

### 4. Структурированные данные (Schema.org)
JSON-LD с типом Person помогает поисковикам понять, что это персональная страница специалиста.

---

## Что нужно настроить под себя

### 1. Canonical URL и домен
В `index.html` сейчас указан `https://sergeymarkin.ru/`. Если домен другой — замените во всех тегах:
- `og:url`
- `og:image`
- `twitter:image`
- `canonical`
- в JSON-LD: `url`, `image`

### 2. Картинка для соцсетей
- Путь: `img/Обложка профиля.jpg`
- Рекомендуемый размер: 1200×630 px
- Формат: JPG или PNG

### 3. Подключение к поисковикам

**Яндекс:**
1. Зайдите в [Яндекс.Вебмастер](https://webmaster.yandex.ru/)
2. Добавьте сайт
3. Подтвердите владение (HTML-файл или meta-тег)

**Google:**
1. Зайдите в [Google Search Console](https://search.google.com/search-console)
2. Добавьте ресурс
3. Подтвердите владение

### 4. Sitemap (опционально)
Для одной страницы sitemap не обязателен. Если появятся новые страницы — создайте `sitemap.xml` и укажите его в Вебмастере и Search Console.

---

## Проверка

- **Open Graph:** [opengraph.xyz](https://www.opengraph.xyz/) — вставьте URL и посмотрите превью
- **Структурированные данные:** [validator.schema.org](https://validator.schema.org/) — проверка JSON-LD
- **Мобильная версия:** [Google Mobile-Friendly Test](https://search.google.com/test/mobile-friendly)
