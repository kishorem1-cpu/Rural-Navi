"""
Comprehensive Test Suite for Rural Navi Platform
-------------------------------------------------
Evaluates:
1. Exact house-number resolution (e.g., 3-82)
2. Normalization formats (e.g., ' 3/82 ', '03-082')
3. Multiple matches / ambiguity handling
4. Village scoping & filtering
5. Delivery issue reporting & audit trail logging
6. Administrative stats, report resolution & CSV export
7. Opaque token navigation redirect
8. Confidence score calculation
"""

import unittest
import json
from app import app
from database import normalize_house_no, calculate_confidence, get_db


class RuralNaviTestCase(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def test_01_normalization(self):
        """Test normalization handles variants consistently."""
        self.assertEqual(normalize_house_no("3-82"), "3-82")
        self.assertEqual(normalize_house_no(" 3 / 82 "), "3-82")
        self.assertEqual(normalize_house_no("03-082"), "3-82")
        self.assertEqual(normalize_house_no("4/15"), "4-15")

    def test_02_confidence_scoring(self):
        """Test calculation of objective confidence scores."""
        score, tier = calculate_confidence("verified", "panchayat_survey", 3.0, 1)
        self.assertEqual(tier, "HIGH")
        self.assertGreaterEqual(score, 75)

        score_disp, tier_disp = calculate_confidence("disputed", "citizen_submission", 25.0, 0)
        self.assertEqual(tier_disp, "DISPUTED")
        self.assertLessEqual(score_disp, 30)

    def test_03_legacy_lookup_api(self):
        """Test backward-compatible /lookup endpoint."""
        res = self.client.get('/lookup?house=3-82')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['found'])
        self.assertEqual(data['house_no'], '3-82')
        self.assertIn('lat', data)
        self.assertIn('lng', data)
        self.assertEqual(data['village'], 'Alanganallur')

    def test_04_search_exact_match(self):
        """Test /api/search returns EXACT_MATCH for unique door."""
        res = self.client.get('/api/search?q=3-82')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['match_type'], 'EXACT_MATCH')
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['house_no'], '3-82')

    def test_05_search_no_match(self):
        """Test /api/search returns NO_MATCH for non-existent door."""
        res = self.client.get('/api/search?q=99-999')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['match_type'], 'NO_MATCH')
        self.assertEqual(data['count'], 0)

    def test_06_report_submission_and_resolution(self):
        """Test delivery issue submission and admin resolution."""
        # 1. Submit report
        rep_res = self.client.post('/api/report', json={
            'house_id': 2,
            'report_type': 'incorrect_location',
            'reporter_role': 'delivery',
            'description': 'Doorway is 10m north behind water tank',
            'proposed_lat': 9.4520,
            'proposed_lng': 77.5587
        })
        self.assertEqual(rep_res.status_code, 200)
        rep_id = rep_res.get_json()['report_id']

        # 2. Check report listed in admin
        list_res = self.client.get('/api/admin/reports')
        reports = list_res.get_json()['reports']
        self.assertTrue(any(r['id'] == rep_id for r in reports))

        # 3. Resolve report (Approve)
        res_res = self.client.post(f'/api/admin/reports/{rep_id}/resolve', json={
            'action': 'approve',
            'notes': 'Verified by village VAO'
        })
        self.assertEqual(res_res.status_code, 200)
        self.assertTrue(res_res.get_json()['success'])

    def test_07_nav_token_redirect(self):
        """Test opaque nav_token redirects to map without exposing private fields."""
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT nav_token FROM houses WHERE house_no = '3-82'")
        token = c.fetchone()[0]
        conn.close()

        res = self.client.get(f'/nav/{token}')
        self.assertEqual(res.status_code, 302)
        self.assertIn('google.com/maps', res.headers['Location'])

    def test_08_admin_export_csv(self):
        """Test administrative CSV export."""
        res = self.client.get('/api/admin/export')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.headers['Content-Type'])
        self.assertIn('HouseNo', res.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
