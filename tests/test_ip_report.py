import copy
from io import BytesIO
from pathlib import Path
import sys
import unittest

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'financial-analysis/scripts'))
from render_report import read_json, render


class IPReportTest(unittest.TestCase):
    def setUp(self):
        self.data = read_json(ROOT / 'examples/ip-report.json')
        self.position = {
            'borrower_id': self.data['borrower_id'], 'assessment_date': self.data['as_of'],
            'currency': self.data['currency'],
            'obligation_calendar': {
                'horizon': {'start': '2026-01-01', 'end_exclusive': '2026-07-01'},
                'events': [
                    {'date': '2026-03-15', 'amount': '13000.00', 'date_basis': 'documented_payment_date'},
                    {'date': '2026-01-01', 'amount': '99000000.00', 'date_basis': 'scenario_assumption'},
                ],
                'complete': False, 'confirmed_schedule_complete': False,
            },
        }

    def pdf_text(self, data, position=None):
        pdf = PdfReader(BytesIO(render(data, position)))
        self.assertEqual(len(pdf.pages), 1)
        return pdf.pages[0].extract_text()

    def test_sparse_history_and_partial_debt_are_explicit(self):
        self.data.pop('layout')
        self.data['financial']['ip']['monthly_receipts'].pop(5)
        text = self.pdf_text(self.data, self.position)
        for value in ('742', '0,024 млн USD', '0,0144 млн USD', '0,013 млн USD',
                      'Нет графика', 'н/д: нет данных за месяц', '06.25'):
            self.assertIn(value, text)
        self.assertNotIn('99,000', text)
        self.assertNotIn('—', text)

    def test_complete_debt_can_display_zero_months(self):
        calendar = self.position['obligation_calendar']
        calendar['events'].pop()
        calendar.update(complete=True, confirmed_schedule_complete=True)
        text = self.pdf_text(self.data, self.position)
        self.assertIn('График подтверждён', text)
        self.assertNotIn('Нет графика', text)
        self.assertIn('0,013', text)

    def test_legacy_ip_input_keeps_the_ip_layout(self):
        legacy = copy.deepcopy(self.data)
        legacy['layout'] = 'coverage'
        legacy['financial'].pop('ip')
        text = self.pdf_text(legacy)
        self.assertIn('Помесячные поступления по выпискам не установлены', text)
        self.assertIn('Нет графика', text)
        self.assertIn('742', text)
        self.assertNotIn('—', text)

    def test_company_statement_keeps_its_own_layout(self):
        text = self.pdf_text(read_json(ROOT / 'examples/report.json'))
        self.assertIn('Финансовое состояние', text)
        self.assertIn('Поступления и погашения', text)


if __name__ == '__main__':
    unittest.main()
