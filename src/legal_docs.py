"""Публичные юридические документы сервиса."""

from __future__ import annotations

from config import config

DOC_DATE = "25 августа 2026 г."


def _support_line() -> str:
    url = (config.SUPPORT_URL or "").strip()
    email = (getattr(config, "SUPPORT_EMAIL", "") or "").strip()
    parts: list[str] = []
    if url:
        parts.append(url)
    if email:
        parts.append(email)
    return " · ".join(parts) if parts else "через Telegram-бота"


def _plan_price() -> tuple[str, int]:
    try:
        from payments import PLANS

        plan = next(iter(PLANS.values()), None)
        if plan:
            return plan.title, plan.price_rub
    except Exception:
        pass
    return "1 месяц", 69


def _css() -> str:
    return """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Syne:wght@600;700;800&display=swap');
:root {
  --bg: #09060f;
  --bg-2: #110818;
  --paper: rgba(24, 14, 42, 0.92);
  --ink: #f3eefc;
  --muted: #a89bc4;
  --line: rgba(167, 139, 250, 0.22);
  --accent: #8b5cf6;
  --accent-2: #c4b5fd;
  --accent-soft: rgba(139, 92, 246, 0.2);
  --shadow: 0 18px 50px rgba(4, 0, 12, 0.45);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(ellipse 80% 50% at 8% -8%, rgba(139,92,246,0.32), transparent 55%),
    radial-gradient(ellipse 55% 40% at 100% 0%, rgba(76,29,149,0.4), transparent 50%),
    radial-gradient(circle at 50% 110%, rgba(91,33,182,0.14), transparent 42%),
    linear-gradient(180deg, var(--bg-2) 0%, var(--bg) 100%);
  font-family: Manrope, system-ui, sans-serif;
  line-height: 1.6;
  min-height: 100vh;
}
.wrap { max-width: 820px; margin: 0 auto; padding: 28px 18px 72px; }
.top {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  justify-content: space-between; margin-bottom: 28px;
}
.brand {
  font-family: Syne, Manrope, system-ui, sans-serif;
  font-weight: 800; letter-spacing: -0.03em; font-size: 1.15rem;
  text-decoration: none; color: var(--ink); line-height: 1.15;
}
.brand em {
  display: block; font-style: normal; font-size: 0.62rem;
  letter-spacing: 0.24em; text-transform: uppercase; color: var(--accent-2);
  font-weight: 700; margin-top: 2px;
}
.brand:hover { color: var(--accent-2); }
.nav { display: flex; flex-wrap: wrap; gap: 8px; }
.nav a {
  text-decoration: none; color: var(--muted); font-size: 0.92rem; font-weight: 600;
  padding: 8px 12px; border-radius: 999px; background: rgba(12,6,22,0.75);
  border: 1px solid var(--line);
}
.nav a:hover { color: var(--accent-2); border-color: rgba(167,139,250,0.45);
  background: rgba(139,92,246,0.12); }
.hero {
  background: var(--paper); border: 1px solid var(--line); border-radius: 24px;
  padding: 28px 24px; box-shadow: var(--shadow); margin-bottom: 18px;
  backdrop-filter: blur(10px); position: relative; overflow: hidden;
}
.hero::before {
  content: ""; position: absolute; inset: 0 auto auto 0; width: 100%; height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent); opacity: .75;
}
.hero h1 {
  margin: 0 0 8px; font-family: Syne, Manrope, system-ui, sans-serif;
  font-size: clamp(1.7rem, 4vw, 2.4rem); line-height: 1.12; letter-spacing: -0.03em;
  font-weight: 800;
  background: linear-gradient(120deg, #f5f0ff, #c4b5fd 55%, #8b5cf6);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.meta { color: var(--muted); margin: 0; font-size: 0.95rem; }
.card {
  background: var(--paper); border: 1px solid var(--line); border-radius: 20px;
  padding: 22px 20px; margin: 14px 0; box-shadow: var(--shadow);
}
.card h2 {
  margin: 0 0 10px; font-size: 1.05rem; letter-spacing: -0.01em; color: var(--accent-2);
}
.price {
  display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end;
  justify-content: space-between; margin-top: 8px;
}
.price .amount {
  font-family: Syne, Manrope, system-ui, sans-serif;
  font-size: 2.4rem; font-weight: 800; letter-spacing: -0.04em; line-height: 1;
  color: var(--accent-2);
}
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--accent-soft); color: var(--accent-2);
  border-radius: 999px; padding: 8px 12px; font-size: 0.86rem; font-weight: 700;
  border: 1px solid var(--line); letter-spacing: 0.04em; text-transform: uppercase;
}
table { width: 100%; border-collapse: collapse; }
th, td { padding: 12px 10px; border-bottom: 1px solid var(--line); text-align: left; }
th { color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: .08em; }
tr:hover td { background: rgba(139,92,246,0.06); }
ul { margin: 8px 0 0; padding-left: 1.15em; }
li { margin: 4px 0; }
p { margin: 0 0 12px; }
.section h2 {
  margin: 28px 0 10px; font-size: 1.15rem;
  font-family: Syne, Manrope, system-ui, sans-serif; color: var(--accent-2);
}
.footer {
  margin-top: 28px; color: var(--muted); font-size: 0.88rem;
  display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
}
.marker {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: rgba(12,6,22,0.85); border: 1px solid var(--line); border-radius: 8px;
  padding: 4px 8px; color: var(--accent-2);
}
.cta {
  display: inline-block; margin-top: 8px; text-decoration: none;
  background: linear-gradient(135deg, #7c3aed, #6d28d9 55%, #5b21b6);
  color: #fff; font-weight: 700;
  padding: 12px 16px; border-radius: 12px;
  box-shadow: 0 8px 24px rgba(109,40,217,0.4);
}
.cta:hover { filter: brightness(1.06); }
@media (max-width: 640px) {
  .hero, .card { padding: 20px 16px; border-radius: 18px; }
}
"""


def _shell(title: str, body: str) -> str:
    name = config.BOT_NAME or "TsuloVPN"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} · {name} Nexus</title>
<style>{_css()}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a class="brand" href="/">{name}<em>Nexus</em></a>
    <nav class="nav">
      <a href="/tariffs">Тарифы</a>
      <a href="/privacy">Конфиденциальность</a>
      <a href="/terms">Соглашение</a>
      <a href="{config.SUPPORT_URL}">Поддержка</a>
    </nav>
  </div>
  {body}
  <div class="footer">
    <span>{name} Nexus · VPN-доступ</span>
  </div>
</div>
</body>
</html>"""


def tariffs_html() -> str:
    name = config.BOT_NAME or "TsuloVPN"
    from devices import (
        BASE_MONTHLY_PRICE,
        FIRST_EXTRA_SLOT_PRICE,
        MAX_DEVICE_SLOTS,
        pack_options,
    )

    packs = pack_options()
    rows = "\n".join(
        f"<tr><td>{o['devices']} устр.</td><td><b>{o['price_rub']} ₽</b> / мес</td></tr>"
        for o in packs
    )
    free_note = (
        "Ниже — стоимость. Актуальный статус оплаты смотрите в Telegram-боте."
        if not config.payments_active
        else "В боте выберите пакет «месяц + устройства» — одна оплата активирует доступ и лимит."
    )
    return _shell(
        "Тарифы",
        f"""
<section class="hero">
  <p class="meta">Актуально на {DOC_DATE}</p>
  <h1>Тарифы и цены</h1>
  <p class="meta">Месяц доступа + нужное число устройств — одной оплатой</p>
</section>
<section class="card">
  <span class="badge">Nexus · пакеты</span>
  <p style="margin:12px 0">База <b>{BASE_MONTHLY_PRICE} ₽</b> (1 устройство).
  Доп. слот от <b>{FIRST_EXTRA_SLOT_PRICE} ₽</b>, максимум {MAX_DEVICE_SLOTS}.</p>
  <table>
    <thead><tr><th>Устройства</th><th>Цена</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
  <p style="margin-top:16px">{free_note}</p>
</section>
<section class="card">
  <h2>Что входит</h2>
  <ul>
    <li>персональный ключ в Telegram-боте;</li>
    <li>автообновление профиля;</li>
    <li>до {MAX_DEVICE_SLOTS} устройств по выбранному пакету;</li>
    <li>техническая поддержка.</li>
  </ul>
</section>
<section class="card">
  <h2>Поддержка</h2>
  <p>По вопросам оплаты и доступа: <b>{_support_line()}</b></p>
  <a class="cta" href="{config.SUPPORT_URL}">Написать в поддержку</a>
</section>
""",
    )


def privacy_html() -> str:
    name = config.BOT_NAME or "TsuloVPN"
    site = (config.SUBSCRIPTION_PUBLIC_URL or "").rstrip("/") or "Telegram-бот"
    return _shell(
        "Политика конфиденциальности",
        f"""
<section class="hero">
  <p class="meta">Дата редакции: {DOC_DATE}</p>
  <h1>Политика конфиденциальности</h1>
  <p class="meta">Сервис {name} · {site}</p>
</section>
<section class="card section">
<p>Политика конфиденциальности регулирует сбор, использование и защиту информации
пользователей сервиса <b>{name}</b>. Собираются идентификаторы аккаунта, техническая
информация и история взаимодействий. Данные используются для обеспечения работы сервиса,
связи с пользователем и анализа. Передача информации третьим лицам возможна только в
законодательно установленных случаях, с согласия пользователя или для исполнения
обязательств (в том числе перед платёжными системами). Хранение данных осуществляется в
течение необходимого срока, их защита — в разумных пределах. Администрация вправе вносить
изменения в Политику без предварительного уведомления — согласие считается принятым при
дальнейшем использовании сервиса.</p>

<h2>1. Общие положения</h2>
<p>1.1. Настоящая Политика конфиденциальности (далее — «Политика») регулирует порядок
обработки и защиты информации, которую Пользователь передаёт при использовании сервиса
{name} (далее — «Сервис»), включая Telegram-бота и связанные веб-страницы.</p>
<p>1.2. Используя Сервис, Пользователь подтверждает согласие с условиями Политики.
Если Пользователь не согласен — он обязан прекратить использование Сервиса.</p>

<h2>2. Сбор информации</h2>
<p>2.1. Сервис может собирать:</p>
<ul>
  <li>идентификаторы аккаунта (Telegram ID, никнейм и т.п.);</li>
  <li>техническую информацию (IP-адрес, данные о браузере, устройстве и ОС);</li>
  <li>историю взаимодействий с Сервисом.</li>
</ul>
<p>2.2. Сервис не требует паспортных данных, документов, фотографий или иной избыточной
личной информации, кроме минимально необходимой для работы.</p>

<h2>3. Использование информации</h2>
<p>3.1. Информация используется исключительно для:</p>
<ul>
  <li>обеспечения работы функционала Сервиса;</li>
  <li>связи с Пользователем (уведомления и поддержка);</li>
  <li>анализа и улучшения работы Сервиса.</li>
</ul>

<h2>4. Передача информации третьим лицам</h2>
<p>4.1. Администрация не передаёт данные третьим лицам, за исключением случаев:</p>
<ul>
  <li>если это требуется по закону;</li>
  <li>если это необходимо для исполнения обязательств перед Пользователем
  (например, при работе с платёжными системами);</li>
  <li>если Пользователь сам дал на это согласие.</li>
</ul>

<h2>5. Хранение и защита данных</h2>
<p>5.1. Данные хранятся в течение срока, необходимого для целей обработки.</p>
<p>5.2. Администрация принимает разумные меры защиты, но не гарантирует абсолютную
безопасность при передаче через интернет.</p>

<h2>6. Отказ от ответственности</h2>
<p>6.1. Пользователь понимает, что передача данных через интернет сопряжена с рисками.</p>
<p>6.2. Администрация не несёт ответственности за утрату, кражу или раскрытие данных,
если это произошло по вине третьих лиц или самого Пользователя.</p>

<h2>7. Изменения в Политике</h2>
<p>7.1. Администрация вправе изменять Политику без предварительного уведомления.</p>
<p>7.2. Продолжение использования Сервиса означает согласие с новой редакцией.</p>

<h2>8. Контакты</h2>
<p>По вопросам обработки данных: <b>{_support_line()}</b></p>
</section>
""",
    )


def terms_html() -> str:
    name = config.BOT_NAME or "TsuloVPN"
    site = (config.SUBSCRIPTION_PUBLIC_URL or "").rstrip("/") or "Telegram-бот"
    return _shell(
        "Пользовательское соглашение",
        f"""
<section class="hero">
  <p class="meta">Дата редакции: {DOC_DATE}</p>
  <h1>Пользовательское соглашение</h1>
  <p class="meta">Сервис {name} · {site}</p>
</section>
<section class="card section">
<h2>1. Общие положения</h2>
<p>1.1. Настоящее Пользовательское соглашение (далее — «Соглашение») регулирует порядок
использования онлайн-сервиса {name} ({site} / Telegram-бот) (далее — «Сервис»),
предоставляемого Администрацией.</p>
<p>1.2. Используя Сервис, включая запуск бота, регистрацию, оплату услуг или получение
доступа, Пользователь подтверждает, что ознакомился с условиями Соглашения и принимает
их в полном объёме.</p>
<p>1.3. В случае несогласия Пользователь обязан прекратить использование Сервиса.</p>

<h2>2. Характер услуг и цифровых товаров</h2>
<p>2.1. Сервис предоставляет цифровые товары и услуги нематериального характера:
доступ к цифровому профилю подключения, информационные материалы и сервисное
сопровождение.</p>
<p>2.2. Материалы и функции Сервиса могут включать информацию из открытых источников,
авторские материалы Администрации и/или третьих лиц, рекомендации и структурированные данные.</p>
<p>2.3. Ценность услуг заключается в систематизации, форме подачи, сопровождении,
поддержке и обновлениях.</p>
<p>2.4. Сервис не заявляет уникальность отдельных элементов материалов вне Сервиса.</p>

<h2>3. Отказ от гарантий и ответственности</h2>
<p>3.1. Сервис предоставляется на условиях «AS IS» («как есть»).</p>
<p>3.2. Администрация не гарантирует соответствие ожиданиям Пользователя, достижение
каких-либо результатов, а также бесперебойную и безошибочную работу Сервиса.</p>
<p>3.3. Администрация не несёт ответственности за прямые или косвенные убытки,
действия третьих лиц и временные технические сбои.</p>
<p>3.4. Решения о применении материалов и услуг принимаются Пользователем самостоятельно
и на его риск.</p>

<h2>4. Законность использования</h2>
<p>4.1. Сервис не предназначен для поощрения или содействия противоправной деятельности.</p>
<p>4.2. Пользователь обязуется использовать Сервис в рамках применимого законодательства
и правил третьих сторон.</p>
<p>4.3. Ответственность за законность использования полностью возлагается на Пользователя.</p>

<h2>5. Интеллектуальная собственность</h2>
<p>5.1. Материалы Сервиса охраняются законодательством об интеллектуальной собственности.</p>
<p>5.2. Запрещается копировать, распространять, перепродавать или передавать материалы
без разрешения правообладателя.</p>
<p>5.3. Нарушение может повлечь ограничение доступа без компенсации.</p>

<h2>6. Ограничение доступа</h2>
<p>6.1. Администрация вправе приостановить или ограничить доступ при нарушении Соглашения,
злоупотреблениях либо по требованиям законодательства или платёжных провайдеров.</p>
<p>6.2. Ограничение доступа не освобождает от ранее возникших обязательств.</p>
<p>6.3. Администрация вправе отказывать в обслуживании при повышенных рисках для Сервиса
или платёжных провайдеров.</p>

<h2>7. Платежи и возвраты</h2>
<p>7.1. Оплата производится на условиях, указанных в Сервисе до момента оплаты
(см. раздел «Тарифы»).</p>
<p>7.2. В связи с нематериальным характером цифровых услуг возврат после предоставления
доступа не осуществляется, кроме случаев ниже.</p>
<p>7.3. Возврат возможен, если услуга не оказана по технической вине Сервиса либо доступ
фактически не был предоставлен.</p>
<p>7.4. Для возврата нужно обратиться в поддержку в течение 24 часов с момента оплаты.</p>
<p>7.5. Решение о возврате принимается Администрацией индивидуально.</p>
<p>7.6. Пользователь обязуется не инициировать chargeback без предварительного обращения
в поддержку Сервиса.</p>

<h2>8. Конфиденциальность</h2>
<p>8.1. Администрация может собирать минимально необходимые технические данные.</p>
<p>8.2. Принимаются разумные меры защиты, абсолютная безопасность не гарантируется.</p>

<h2>9. Изменение условий</h2>
<p>9.1. Администрация вправе изменять Соглашение.</p>
<p>9.2. Актуальная версия публикуется в Сервисе (эта страница).</p>
<p>9.3. Продолжение использования означает согласие с обновлёнными условиями.</p>

<h2>10. Контактная информация</h2>
<p>10.1. Поддержка: <b>{_support_line()}</b></p>
<p>Используя Сервис (в том числе запуская бота и/или команду /start), Пользователь
подтверждает, что ознакомлен с Соглашением и принимает его условия.</p>
</section>
""",
    )
