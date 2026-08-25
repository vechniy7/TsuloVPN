"""Публичные документы для согласования с банком / платёжным провайдером."""

from __future__ import annotations

from config import config

DOC_DATE = "25 августа 2026 г."
BANK_MARKER = "плаtega"


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
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap');
:root {
  --bg: #f3f1ec;
  --paper: #fffcf7;
  --ink: #171717;
  --muted: #5c5a55;
  --line: #e4dfd4;
  --accent: #0f6e56;
  --accent-soft: #e7f4ef;
  --shadow: 0 18px 50px rgba(23, 23, 23, 0.06);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(circle at top left, rgba(15,110,86,0.08), transparent 28%),
    linear-gradient(180deg, #f7f5f0 0%, var(--bg) 100%);
  font-family: Manrope, system-ui, sans-serif;
  line-height: 1.6;
}
.wrap { max-width: 820px; margin: 0 auto; padding: 28px 18px 72px; }
.top {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  justify-content: space-between; margin-bottom: 28px;
}
.brand {
  font-weight: 700; letter-spacing: -0.02em; font-size: 1.05rem;
  text-decoration: none; color: var(--ink);
}
.nav { display: flex; flex-wrap: wrap; gap: 8px; }
.nav a {
  text-decoration: none; color: var(--muted); font-size: 0.92rem;
  padding: 8px 12px; border-radius: 999px; background: rgba(255,255,255,0.65);
  border: 1px solid var(--line);
}
.nav a:hover { color: var(--ink); border-color: #cfc8ba; }
.hero {
  background: var(--paper); border: 1px solid var(--line); border-radius: 24px;
  padding: 28px 24px; box-shadow: var(--shadow); margin-bottom: 18px;
}
.hero h1 {
  margin: 0 0 8px; font-family: "Source Serif 4", Georgia, serif;
  font-size: clamp(1.7rem, 4vw, 2.3rem); line-height: 1.15; letter-spacing: -0.02em;
}
.meta { color: var(--muted); margin: 0; font-size: 0.95rem; }
.card {
  background: var(--paper); border: 1px solid var(--line); border-radius: 20px;
  padding: 22px 20px; margin: 14px 0; box-shadow: var(--shadow);
}
.card h2 {
  margin: 0 0 10px; font-size: 1.05rem; letter-spacing: -0.01em;
}
.price {
  display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end;
  justify-content: space-between; margin-top: 8px;
}
.price .amount {
  font-size: 2.4rem; font-weight: 700; letter-spacing: -0.04em; line-height: 1;
}
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--accent-soft); color: var(--accent);
  border-radius: 999px; padding: 8px 12px; font-size: 0.86rem; font-weight: 600;
}
ul { margin: 8px 0 0; padding-left: 1.15em; }
li { margin: 4px 0; }
p { margin: 0 0 12px; }
.section h2 {
  margin: 28px 0 10px; font-size: 1.15rem;
  font-family: "Source Serif 4", Georgia, serif;
}
.footer {
  margin-top: 28px; color: var(--muted); font-size: 0.88rem;
  display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
}
.marker {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: #fff; border: 1px solid var(--line); border-radius: 8px;
  padding: 4px 8px; color: var(--ink);
}
.cta {
  display: inline-block; margin-top: 8px; text-decoration: none;
  background: var(--accent); color: #fff; font-weight: 600;
  padding: 12px 16px; border-radius: 12px;
}
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
<title>{title} · {name}</title>
<style>{_css()}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a class="brand" href="/">{name}</a>
    <nav class="nav">
      <a href="/tariffs">Тарифы</a>
      <a href="/privacy">Конфиденциальность</a>
      <a href="/terms">Соглашение</a>
      <a href="{config.SUPPORT_URL}">Поддержка</a>
    </nav>
  </div>
  {body}
  <div class="footer">
    <span>{name} · цифровой сервис доступа</span>
    <span>код согласования: <span class="marker">{BANK_MARKER}</span></span>
  </div>
</div>
</body>
</html>"""


def tariffs_html() -> str:
    name = config.BOT_NAME or "TsuloVPN"
    title, price = _plan_price()
    free_note = (
        "Сейчас доступ предоставляется бесплатно для всех пользователей. "
        "Ниже указана актуальная стоимость подписки сервиса."
        if not config.payments_active
        else "Оплата активирует подписку на выбранный срок."
    )
    return _shell(
        "Тарифы",
        f"""
<section class="hero">
  <p class="meta">Актуально на {DOC_DATE}</p>
  <h1>Тарифы и цены</h1>
  <p class="meta">Прозрачная стоимость цифрового доступа {name}</p>
</section>
<section class="card">
  <span class="badge">один тариф</span>
  <div class="price">
    <div>
      <h2 style="margin-bottom:4px">{title}</h2>
      <p class="meta" style="margin:0">цифровой доступ к профилю · обновления · поддержка</p>
    </div>
    <div class="amount">{price} ₽</div>
  </div>
  <p style="margin-top:16px">{free_note}</p>
</section>
<section class="card">
  <h2>Что входит</h2>
  <ul>
    <li>персональная ссылка профиля в Telegram-боте;</li>
    <li>автоматическое обновление профиля;</li>
    <li>техническая поддержка пользователей.</li>
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
