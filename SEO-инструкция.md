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

## Сайт на Flask (этот проект)

Уже учтено в шаблонах и `app.py`:

- **Мета-теги** на каждой странице: `title`, `description`, `keywords`, `author`, `canonical`, `robots`.
- **Open Graph** и **Twitter Card** с заголовком, описанием и картинкой (на странице кейса — своя картинка).
- **JSON-LD Person** на публичных страницах; на странице кейса дополнительно **BreadcrumbList**.
- **`robots.txt`** — разрешена индексация, закрыт `/admin`; указан путь к sitemap.
- **`/sitemap.xml`** — главная, `/cases`, `/contact`, все страницы кейсов.

Домен и картинка по умолчанию задаются в **`config.py`**:

- `SITE_URL` — канонический адрес (по умолчанию `https://sergeymarkin.ru`). В продакшене задайте переменную окружения `SITE_URL`, если домен другой.
- `SEO_OG_IMAGE` — путь к превью для соцсетей (по умолчанию `/static/images/hero-profile.svg`). Можно заменить на JPG 1200×630 в `static/images/` и прописать путь в переменной `SEO_OG_IMAGE`.

Проверка превью: после деплоя вставьте полный URL сайта на [opengraph.xyz](https://www.opengraph.xyz/).

---

## Проверка

- **Open Graph:** [opengraph.xyz](https://www.opengraph.xyz/) — вставьте URL и посмотрите превью
- **Структурированные данные:** [validator.schema.org](https://validator.schema.org/) — проверка JSON-LD
- **Мобильная версия:** [Google Mobile-Friendly Test](https://search.google.com/test/mobile-friendly)
