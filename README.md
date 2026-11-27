# Financial analysis skill

Навык анализирует финансы компании или ИП по отчётности, банковским выпискам и документам по долгам. Итоговый PDF использует фирменный макет ВБетон. На листе финансовой истории есть график поступлений и погашений. Если вы предоставите кредитный отчёт, в шапке появится рейтинг бюро на его исходной шкале. Для работы достаточно ваших документов и среды с Python.

- По отчётности рассчитывает долговую нагрузку, ликвидность и покрытие процентов. При известных условиях нового займа сравнивает показатели до и после выдачи.
- По выпискам сверяет остатки и обороты, помогает разобрать пересекающиеся выгрузки и исключить подтверждённые переводы между своими счетами.
- По документам о долге строит календарь платежей. При достаточных данных рассчитывает покрытие прежних обязательств на шесть месяцев и показывает, когда возникает кассовый разрыв.

Каждый расчёт использует одну указанную валюту. Скрипты выписок и графиков поддерживают суммы с двумя десятичными знаками. Проверка документов и классификация операций выполняются в ходе анализа. В PDF можно указать известную часть суммы и объяснить, чего не хватает для полного итога.

## Скачать

Скачайте репозиторий через **Code → Download ZIP** и распакуйте. Сам навык находится в папке [financial-analysis](financial-analysis/). Команды ниже запускаются из каталога репозитория.

## Claude Code

Скопируйте папку навыка в персональный каталог Claude Code. [Документация Claude Code](https://code.claude.com/docs/en/skills)

```sh
mkdir -p "$HOME/.claude/skills"
cp -R financial-analysis "$HOME/.claude/skills/"
```

Для одного проекта используйте `.claude/skills/` в корне проекта. Откройте новую сессию и вызовите `/financial-analysis`.

## Claude и Cowork

Скачайте [готовый ZIP навыка](financial-analysis.zip). Откройте **Customize → Skills → Create skill → Upload a skill** и загрузите архив. Включите выполнение кода и создание файлов в настройках Claude. Для Cowork навык включается в том же аккаунте. [Установка навыков в Claude](https://support.claude.com/en/articles/12512180-use-skills-in-claude)

Архив содержит одну корневую папку `financial-analysis/`. [Формат архива Claude](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)

## OpenAI Codex

Скопируйте навык в персональный каталог Codex. Этот способ подходит для локального Codex в настольном приложении, CLI и расширении IDE. [OpenAI Docs о навыках](https://learn.chatgpt.com/docs/build-skills)

```sh
mkdir -p "$HOME/.agents/skills"
cp -R financial-analysis "$HOME/.agents/skills/"
```

Для одного проекта используйте `.agents/skills/` в его корне. Откройте новую сессию, выберите навык в списке или вызовите `$financial-analysis`. В настольном приложении доступные навыки можно проверить в разделе **Skills**. Для распространения через каталог ChatGPT, включая веб-чат, OpenAI использует плагины. [OpenAI Docs о распространении навыков](https://learn.chatgpt.com/docs/build-skills)

## OpenAI Responses API

1. Скачайте [готовый ZIP навыка](financial-analysis.zip).
2. Загрузите архив и сохраните возвращённые `id` и `default_version`. Перед подключением дождитесь доступности версии через `GET /v1/skills/{skill_id}/versions/{version}`. [OpenAI Docs о загрузке навыка](https://developers.openai.com/api/docs/guides/tools-skills)
   ```sh
   curl -fsS https://api.openai.com/v1/skills \
     -H "Authorization: Bearer $OPENAI_API_KEY" \
     -F 'files=@financial-analysis.zip;type=application/zip'
   ```

3. При вызове Responses API передайте ID и версию в `skills` среды инструмента `shell`. Передайте согласованные документы в контейнер и попросите модель использовать навык. [OpenAI Docs о shell и навыках](https://developers.openai.com/api/docs/guides/tools-shell)

```json
{
  "type": "shell",
  "environment": {
    "type": "container_auto",
    "skills": [
      {"type": "skill_reference", "skill_id": "skill_ID_FROM_UPLOAD", "version": "VERSION_FROM_UPLOAD"}
    ]
  }
}
```

## Запуск анализа

Откройте сессию в папке с вашими документами или приложите файлы к чату. Например:

> Используй financial-analysis. Проанализируй финансовое состояние компании по отчётности, выпискам и графикам платежей по состоянию на 31 декабря 2025 года. Проверь, хватает ли средств на ближайшие шесть месяцев. Покажи, где вывод ограничен, и подготовь фирменный PDF, а источники с номерами страниц сохрани во входных данных отчёта.

Локальный запуск требует Python 3.11 или новее. Для PDF установите зависимости в свою рабочую среду. [Команды расчёта и OCR](financial-analysis/references/tools.md)

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r financial-analysis/scripts/requirements.txt
```

В [учебном примере](examples/README.md) можно повторить расчёт. Готовые PDF доступны для [компании](examples/financial-report.pdf) и [ИП](examples/financial-ip-report.pdf). Шрифты Roboto Flex распространяются по [SIL Open Font License](financial-analysis/assets/fonts/OFL-RobotoFlex.txt).
