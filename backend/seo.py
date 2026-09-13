# -*- coding: utf-8 -*-
"""SEO: генерация микроразметки Schema.org (JSON-LD) и канонического контекста страниц."""
from __future__ import annotations

from typing import Any
from fastapi import Request
from config import Config


def build_person_ld(site: str, og_img: str) -> dict[str, Any]:
    """Генерация микроразметки Schema.org/Person для эксперта."""
    return {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": "Сергей Маркин",
        "jobTitle": "AI-инженер, архитектор автоматизации бизнес-процессов",
        "description": (
            "AI-инженер и архитектор автоматизации бизнес-процессов. "
            "Разработка и внедрение RAG-ассистентов по базам знаний компании, "
            "сквозных сценариев n8n, корпоративных чат-ботов в Telegram и AI-продуктов для сокращения рутины."
        ),
        "url": site + "/",
        "image": og_img,
        "email": "sergeymarkin@yandex.ru",
        "sameAs": ["https://t.me/sergeymarkin"],
        "knowsAbout": [
            "Внедрение искусственного интеллекта",
            "Разработка AI ассистентов для бизнеса",
            "RAG-системы и корпоративные базы знаний",
            "Автоматизация бизнес-процессов",
            "Сценарии n8n и сквозная интеграция",
            "Чат-боты в Telegram для бизнеса",
            "Анализ качества звонков Whisper",
            "Интеграция CRM (amoCRM, Bitrix24)",
            "Скрининг резюме нейросетью",
            "Промпт-инжиниринг",
            "Artificial Intelligence",
            "AI Agents",
            "Prompt Engineering",
            "RAG Systems",
            "Vector Databases",
            "FAISS",
            "n8n Automation",
            "Telegram Bots",
            "Python",
            "FastAPI",
            "Flutter",
        ],
    }


def build_service_ld(site: str, og_img: str) -> dict[str, Any]:
    """Генерация микроразметки Schema.org/ProfessionalService с каталогом ключевых услуг."""
    return {
        "@context": "https://schema.org",
        "@type": "ProfessionalService",
        "name": "Сергей Маркин — Внедрение искусственного интеллекта и автоматизация бизнеса",
        "image": og_img,
        "url": site + "/",
        "email": "sergeymarkin@yandex.ru",
        "priceRange": "$$",
        "address": {
            "@type": "PostalAddress",
            "addressCountry": "RU",
        },
        "hasOfferCatalog": {
            "@type": "OfferCatalog",
            "name": "Услуги внедрения искусственного интеллекта и автоматизации",
            "itemListElement": [
                {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": "Разработка RAG-ассистентов по корпоративным базам знаний",
                        "description": "Внедрение умных ботов для ответов по документам, регламентам и инструкциям компании 24/7 без галлюцинаций с переводом на оператора.",
                    },
                },
                {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": "Сквозная автоматизация процессов и интеграция на n8n",
                        "description": "Интеграция CRM (amoCRM, Bitrix24), мессенджеров, почты и LLM-обработки для отделов продаж и клиентского сервиса.",
                    },
                },
                {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": "Разработка чат-ботов в Telegram с искусственным интеллектом",
                        "description": "Квалификация лидов, скоринг заявок, автоматическая запись клиентов на консультации.",
                    },
                },
                {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": "Экспресс-аудит бизнес-процессов для внедрения ИИ",
                        "description": "Анализ рутины компании, поиск точек внедрения нейросетей с максимальным ROI за 24–48 часов. Пилот за 5 дней.",
                    },
                },
                {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": "Автоматический контроль и анализ качества звонков (Whisper + LLM)",
                        "description": "Распознавание речи звонков отдела продаж, скоринг по чеклистам, выявление возражений и отправка аналитики в CRM.",
                    },
                },
                {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": "Автоматизация первичного отбора и скрининга резюме для HR",
                        "description": "Мгновенный AI-анализ входящих откликов, скоринг кандидатов по требованиям вакансии и фильтрация нерелевантных резюме.",
                    },
                },
            ],
        },
    }


def get_seo_context(request: Request) -> dict[str, Any]:
    """Сборка полного SEO-контекста для передачи в базовый Jinja2 шаблон."""
    site = Config.SITE_URL.rstrip("/")
    path = request.url.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    canonical = site + path
    og_img = site + (Config.SEO_OG_IMAGE or "/static/images/hero-profile.jpg")

    return {
        "site_url": site,
        "canonical_url": canonical,
        "seo_og_image": og_img,
        "seo_person_ld": build_person_ld(site, og_img),
        "seo_service_ld": build_service_ld(site, og_img),
    }
