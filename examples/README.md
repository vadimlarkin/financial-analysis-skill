# Вымышленный пример

В примере один счёт, 24 операции и один действующий заём. Корпоративный лист дополнен отдельными условными данными по трём годам и новому займу. Документы и суммы вымышлены. Источники указаны в [учебной выписке](statement.csv) и [пояснениях](source-notes.txt).

Из каталога `examples` запустите команды ниже. Для PDF потребуются зависимости из [инструкции](../README.md#запуск-анализа).

```sh
mkdir -p out
scripts=../financial-analysis/scripts
python "$scripts/analyze.py" accounting.json out/accounting-result.json
python "$scripts/import_statement_csv.py" statement.csv statement-profile.json out/import-result.json
python -c 'import json, pathlib; p = pathlib.Path("out"); result = json.loads((p / "import-result.json").read_text()); (p / "bank-result.json").write_text(json.dumps(result["summary"]))'
python "$scripts/summarize_debt_register.py" debt.json out/debt-result.json
python "$scripts/analyze_cash_position.py" cash-position.json out/cash-position-result.json
python "$scripts/render_report.py" report.json out/financial-report.pdf
python "$scripts/render_report.py" ip-report.json out/financial-ip-report.pdf --cash-position out/cash-position-result.json
```

Выписка даёт 24 000 USD поступлений и 14 400 USD списаний. Чистый поток бизнеса до выплат кредиторам составляет 9 600 USD за год. При поступлении потока в конце каждого месяца максимальный дефицит составляет 1 000 USD на 15 марта 2026 года, хотя средств в целом за полугодие хватает. [Вход учебного PDF](report.json)

Готовые формы: [финансовый отчёт компании](financial-report.pdf) и [финансовый отчёт ИП](financial-ip-report.pdf).

Для повторного расчёта используйте копию примера со свежей папкой `out`.
