"""
Synthetic receipt evaluation dataset.

50+ hand-crafted receipt OCR texts covering:
- Simple receipts (clear total, merchant, date)
- Complex receipts (multiple totals, VAT, discounts)
- Edge cases (no date, no merchant, handwritten-style OCR errors)
- Different formats (UK £, US $, EU €)
- Different merchants (Tesco, Starbucks, Uber, Amazon, etc.)

Each entry has ``text`` (simulated OCR output) and ``expected`` (ground-truth
fields). Used by ``test_eval.py`` to measure field-level precision/recall/F1.
"""

from __future__ import annotations

import copy
from typing import Any

EVAL_RECEIPTS: list[dict[str, Any]] = [
    # ── Simple grocery (5) ──────────────────────────────────────────────
    {
        "name": "tesco_simple",
        "text": "TESCO STORES LTD\n25/06/2026\nMilk 1.65\nBread 1.20\nTotal £2.85",
        "expected": {
            "merchant": "TESCO STORES LTD",
            "total": 2.85,
            "date": "2026-06-25",
            "items_count": 2,
        },
    },
    {
        "name": "sainsbury_simple",
        "text": "Sainsbury's Supermarket\n14/03/2026\nApple Juice 2.50\nCereal 3.20\nTotal £5.70",
        "expected": {
            "merchant": "Sainsbury's Supermarket",
            "total": 5.70,
            "date": "2026-03-14",
            "items_count": 2,
        },
    },
    {
        "name": "waitrose_basic",
        "text": "Waitrose & Partners\n01/01/2026\nFree Range Eggs 3.75\nSourdough Bread 2.50\nTotal £6.25",
        "expected": {
            "merchant": "Waitrose & Partners",
            "total": 6.25,
            "date": "2026-01-01",
            "items_count": 2,
        },
    },
    {
        "name": "aldi_basic",
        "text": "ALDI\n10/01/2026\nBananas 0.85\nMilk 1.35\nCheese 2.50\nTotal €4.70",
        "expected": {"merchant": "ALDI", "total": 4.70, "date": "2026-01-10", "items_count": 3},
    },
    {
        "name": "costco_bulk",
        "text": "COSTCO WHOLESALE\n15/02/2026\nToilet Paper 24pk 18.99\nKitchen Towel 12pk 14.50\nTotal $33.49",
        "expected": {
            "merchant": "COSTCO WHOLESALE",
            "total": 33.49,
            "date": "2026-02-15",
            "items_count": 2,
        },
    },
    # ── Restaurant/dining (5) ───────────────────────────────────────────
    {
        "name": "starbucks_coffee",
        "text": "Starbucks Coffee\n05/06/2026\nCaffe Latte 4.50\nBlueberry Muffin 2.75\nTotal £7.25",
        "expected": {
            "merchant": "Starbucks Coffee",
            "total": 7.25,
            "date": "2026-06-05",
            "items_count": 2,
        },
    },
    {
        "name": "mcdonalds_fastfood",
        "text": "McDonald's Restaurant\n12/04/2026\nBig Mac Meal 8.99\nMcFlurry 2.49\nTotal $11.48",
        "expected": {
            "merchant": "McDonald's Restaurant",
            "total": 11.48,
            "date": "2026-04-12",
            "items_count": 2,
        },
    },
    {
        "name": "nandos_dinner",
        "text": "Nando's Chicken\n20/05/2026\n1/4 Chicken 9.50\nChips 3.50\nFrozen Yoghurt 4.00\nTotal £17.00",
        "expected": {
            "merchant": "Nando's Chicken",
            "total": 17.00,
            "date": "2026-05-20",
            "items_count": 3,
        },
    },
    {
        "name": "pizza_hut_delivery",
        "text": "Pizza Hut Delivery\n03/03/2026\nPepperoni Pizza 12.99\nGarlic Bread 3.99\nTotal $16.98",
        "expected": {
            "merchant": "Pizza Hut Delivery",
            "total": 16.98,
            "date": "2026-03-03",
            "items_count": 2,
        },
    },
    {
        "name": "pret_sandwich",
        "text": "Pret A Manger\n08/07/2026\nChicken Sandwich 5.50\nCrisps 1.20\nWater 1.50\nTotal £8.20",
        "expected": {
            "merchant": "Pret A Manger",
            "total": 8.20,
            "date": "2026-07-08",
            "items_count": 3,
        },
    },
    # ── Transport/Uber (5) ──────────────────────────────────────────────
    {
        "name": "uber_ride",
        "text": "UBER *TRIP HELP.UBER.COM\n15/01/2026\nLondon Zone 1-2\nTotal £12.50",
        "expected": {
            "merchant": "UBER *TRIP HELP.UBER.COM",
            "total": 12.50,
            "date": "2026-01-15",
            "items_count": 1,
        },
    },
    {
        "name": "trainline_ticket",
        "text": "TRAINLINE\n22/02/2026\nLondon Kings Cross to Cambridge\nOff-Peak Single £24.90\nTotal £24.90",
        "expected": {
            "merchant": "TRAINLINE",
            "total": 24.90,
            "date": "2026-02-22",
            "items_count": 1,
        },
    },
    {
        "name": "shell_fuel",
        "text": "SHELL STATION M4 J15\n18/03/2026\nUnleaded 95 45.23L\nTotal £62.45",
        "expected": {
            "merchant": "SHELL STATION M4 J15",
            "total": 62.45,
            "date": "2026-03-18",
            "items_count": 1,
        },
    },
    {
        "name": "tfl_travelcard",
        "text": "TFL CONTACTLESS\n25/04/2026\nBus Journey\nTotal £1.75",
        "expected": {
            "merchant": "TFL CONTACTLESS",
            "total": 1.75,
            "date": "2026-04-25",
            "items_count": 1,
        },
    },
    {
        "name": "easyjet_flight",
        "text": "easyJet\n10/05/2026\nLTN to EDI\nFlight EZY1234 £89.99\nTotal €105.50",
        "expected": {
            "merchant": "easyJet",
            "total": 105.50,
            "date": "2026-05-10",
            "items_count": 1,
        },
    },
    # ── Electronics/Amazon (5) ──────────────────────────────────────────
    {
        "name": "amazon_books",
        "text": "Amazon.co.uk\n12/08/2026\nClean Code 42.99\nShipping 0.00\nTotal $42.99",
        "expected": {
            "merchant": "Amazon.co.uk",
            "total": 42.99,
            "date": "2026-08-12",
            "items_count": 1,
        },
    },
    {
        "name": "apple_store",
        "text": "Apple Store Online\n28/09/2026\nAirPods Pro 249.00\nTotal £249.00",
        "expected": {
            "merchant": "Apple Store Online",
            "total": 249.00,
            "date": "2026-09-28",
            "items_count": 1,
        },
    },
    {
        "name": "currys_electronics",
        "text": "Currys PC World\n15/10/2026\nLaptop Charger 29.99\nHDMI Cable 12.99\nTotal £42.98",
        "expected": {
            "merchant": "Currys PC World",
            "total": 42.98,
            "date": "2026-10-15",
            "items_count": 2,
        },
    },
    {
        "name": "best_buy",
        "text": "Best Buy\n05/11/2026\nWireless Mouse 34.99\nMouse Pad 9.99\nTotal $44.98",
        "expected": {
            "merchant": "Best Buy",
            "total": 44.98,
            "date": "2026-11-05",
            "items_count": 2,
        },
    },
    {
        "name": "ebay_purchase",
        "text": "eBay UK\n20/12/2026\nVintage Camera 85.00\nPostage 5.00\nTotal £90.00",
        "expected": {"merchant": "eBay UK", "total": 90.00, "date": "2026-12-20", "items_count": 1},
    },
    # ── UK format with £ (10) ───────────────────────────────────────────
    {
        "name": "boots_pharmacy",
        "text": "BOOTS UK\n04/02/2026\nParacetamol 2.99\nVitamins 12.50\nTotal £15.49",
        "expected": {
            "merchant": "BOOTS UK",
            "total": 15.49,
            "date": "2026-02-04",
            "items_count": 2,
        },
    },
    {
        "name": "tesco_extra",
        "text": "TESCO EXTRA\n16/03/2026\nMeal Deal 3.50\nOrange Juice 2.00\nWater 1.00\nTotal £6.50",
        "expected": {
            "merchant": "TESCO EXTRA",
            "total": 6.50,
            "date": "2026-03-16",
            "items_count": 3,
        },
    },
    {
        "name": "morrisons_shop",
        "text": "Morrisons\n22/04/2026\nChicken Breast 4.50\nBroccoli 1.20\nPotatoes 2.00\nTotal £7.70",
        "expected": {
            "merchant": "Morrisons",
            "total": 7.70,
            "date": "2026-04-22",
            "items_count": 3,
        },
    },
    {
        "name": "asda_weekly",
        "text": "ASDA\n08/05/2026\nPasta 1.00\nTomato Sauce 1.50\nMince 5.00\nTotal £7.50",
        "expected": {"merchant": "ASDA", "total": 7.50, "date": "2026-05-08", "items_count": 3},
    },
    {
        "name": "greggs_breakfast",
        "text": "GREGS\n19/06/2026\nSausage Roll 1.50\nCoffee 2.00\nTotal £3.50",
        "expected": {"merchant": "GREGS", "total": 3.50, "date": "2026-06-19", "items_count": 2},
    },
    {
        "name": "john_lewis",
        "text": "John Lewis\n11/07/2026\nBed Sheets 35.00\nPillowcase 15.00\nTotal £50.00",
        "expected": {
            "merchant": "John Lewis",
            "total": 50.00,
            "date": "2026-07-11",
            "items_count": 2,
        },
    },
    {
        "name": "ikea_furniture",
        "text": "IKEA\n02/08/2026\nMALM Bed Frame 199.00\nLAMP Table 15.00\nTotal £214.00",
        "expected": {"merchant": "IKEA", "total": 214.00, "date": "2026-08-02", "items_count": 2},
    },
    {
        "name": "next_clothing",
        "text": "NEXT Online\n14/09/2026\nJeans 45.00\nT-Shirt 22.00\nTotal £67.00",
        "expected": {
            "merchant": "NEXT Online",
            "total": 67.00,
            "date": "2026-09-14",
            "items_count": 2,
        },
    },
    {
        "name": "british_gas_bill",
        "text": "British Gas\n21/10/2026\nMonthly Direct Debit\nTotal £85.00",
        "expected": {
            "merchant": "British Gas",
            "total": 85.00,
            "date": "2026-10-21",
            "items_count": 1,
        },
    },
    {
        "name": "virgin_media",
        "text": "Virgin Media\n30/11/2026\nBroadband & Phone\nTotal £42.00",
        "expected": {
            "merchant": "Virgin Media",
            "total": 42.00,
            "date": "2026-11-30",
            "items_count": 1,
        },
    },
    # ── US format with $ (10) ───────────────────────────────────────────
    {
        "name": "walmart_grocery",
        "text": "Walmart Supercenter\n03/01/2026\nMilk 3.99\nBread 2.49\nEggs 4.99\nTotal $11.47",
        "expected": {
            "merchant": "Walmart Supercenter",
            "total": 11.47,
            "date": "2026-01-03",
            "items_count": 3,
        },
    },
    {
        "name": "target_shop",
        "text": "Target\n17/02/2026\nLaundry Detergent 12.99\nFabric Softener 7.99\nTotal $20.98",
        "expected": {"merchant": "Target", "total": 20.98, "date": "2026-02-17", "items_count": 2},
    },
    {
        "name": "whole_foods",
        "text": "Whole Foods Market\n28/03/2026\nOrganic Kale 4.99\nAlmond Milk 5.49\nTotal $10.48",
        "expected": {
            "merchant": "Whole Foods Market",
            "total": 10.48,
            "date": "2026-03-28",
            "items_count": 2,
        },
    },
    {
        "name": "trader_joes",
        "text": "Trader Joe's\n09/04/2026\nEverything Bagels 3.49\nCream Cheese 2.99\nOrange Juice 3.99\nTotal $10.47",
        "expected": {
            "merchant": "Trader Joe's",
            "total": 10.47,
            "date": "2026-04-09",
            "items_count": 3,
        },
    },
    {
        "name": "kroger_weekly",
        "text": "Kroger\n14/05/2026\nGround Beef 8.99\nTortillas 3.99\nSalsa 4.49\nTotal $17.47",
        "expected": {"merchant": "Kroger", "total": 17.47, "date": "2026-05-14", "items_count": 3},
    },
    {
        "name": "cvs_pharmacy",
        "text": "CVS Pharmacy\n01/06/2026\nCold Medicine 12.99\nBandages 4.99\nTotal $17.98",
        "expected": {
            "merchant": "CVS Pharmacy",
            "total": 17.98,
            "date": "2026-06-01",
            "items_count": 2,
        },
    },
    {
        "name": "home_depot",
        "text": "Home Depot\n18/07/2026\nPaint Bucket 35.00\nPaintbrush 12.00\nTotal $47.00",
        "expected": {
            "merchant": "Home Depot",
            "total": 47.00,
            "date": "2026-07-18",
            "items_count": 2,
        },
    },
    {
        "name": "amazon_US",
        "text": "Amazon.com\n22/08/2026\nKindle Book 14.99\nUSB-C Cable 9.99\nTotal $24.98",
        "expected": {
            "merchant": "Amazon.com",
            "total": 24.98,
            "date": "2026-08-22",
            "items_count": 2,
        },
    },
    {
        "name": "netflix_subscription",
        "text": "NETFLIX.COM\n03/09/2026\nPremium Plan\nTotal $19.99",
        "expected": {
            "merchant": "NETFLIX.COM",
            "total": 19.99,
            "date": "2026-09-03",
            "items_count": 1,
        },
    },
    {
        "name": "starbucks_us",
        "text": "Starbucks\n11/10/2026\nPumpkin Spice Latte 6.75\nBanana Loaf 3.25\nTotal $10.00",
        "expected": {
            "merchant": "Starbucks",
            "total": 10.00,
            "date": "2026-10-11",
            "items_count": 2,
        },
    },
    # ── EU format with € (5) ────────────────────────────────────────────
    {
        "name": "lidl_germany",
        "text": "LIDL\n06/11/2026\nBread 2.49\nCheese 3.99\nTotal €6.48",
        "expected": {"merchant": "LIDL", "total": 6.48, "date": "2026-11-06", "items_count": 2},
    },
    {
        "name": "zara_clothing",
        "text": "ZARA\n15/12/2026\nTrousers 39.99\nShirt 29.99\nTotal €69.98",
        "expected": {"merchant": "ZARA", "total": 69.98, "date": "2026-12-15", "items_count": 2},
    },
    {
        "name": "hema_store",
        "text": "HEMA\n02/01/2026\nNotebook 3.50\nPens 2.00\nTotal €5.50",
        "expected": {"merchant": "HEMA", "total": 5.50, "date": "2026-01-02", "items_count": 2},
    },
    {
        "name": "booking_hotel",
        "text": "Booking.com\n19/03/2026\nHotel Amsterdam\nTotal €185.00",
        "expected": {
            "merchant": "Booking.com",
            "total": 185.00,
            "date": "2026-03-19",
            "items_count": 1,
        },
    },
    {
        "name": "ikea_eu",
        "text": "IKEA\n24/04/2026\nKALLAX Shelf 79.99\nFRAKTA Bag 3.99\nTotal €83.98",
        "expected": {"merchant": "IKEA", "total": 83.98, "date": "2026-04-24", "items_count": 2},
    },
    # ── No merchant (5) ─────────────────────────────────────────────────
    {
        "name": "no_merchant_1",
        "text": "Receipt\n01/06/2026\nItem 1 10.00\nItem 2 20.00\nTotal £30.00",
        "expected": {"merchant": None, "total": 30.00, "date": "2026-06-01", "items_count": 2},
    },
    {
        "name": "no_merchant_2",
        "text": "25/12/2026\nMilk 2.50\nTotal £2.50",
        "expected": {"merchant": None, "total": 2.50, "date": "2026-12-25", "items_count": 1},
    },
    {
        "name": "no_merchant_3",
        "text": "Invoice #12345\n02/03/2026\nService Fee 50.00\nTotal $50.00",
        "expected": {"merchant": None, "total": 50.00, "date": "2026-03-02", "items_count": 1},
    },
    {
        "name": "no_merchant_4",
        "text": "14/02/2026\nChocolates 15.00\nCard 4.50\nTotal €19.50",
        "expected": {"merchant": None, "total": 19.50, "date": "2026-02-14", "items_count": 2},
    },
    {
        "name": "no_merchant_5",
        "text": "Date: 31/10/2026\nPumpkin 5.00\nCider 8.00\nTotal £13.00",
        "expected": {"merchant": None, "total": 13.00, "date": "2026-10-31", "items_count": 2},
    },
    # ── No date (5) ─────────────────────────────────────────────────────
    {
        "name": "no_date_1",
        "text": "TESCO EXPRESS\nMilk 1.65\nBread 1.20\nTotal £2.85",
        "expected": {"merchant": "TESCO EXPRESS", "total": 2.85, "date": None, "items_count": 2},
    },
    {
        "name": "no_date_2",
        "text": "Starbucks\nCappuccino 3.50\nTotal £3.50",
        "expected": {"merchant": "Starbucks", "total": 3.50, "date": None, "items_count": 1},
    },
    {
        "name": "no_date_3",
        "text": "AMAZON\nKindle eBook 9.99\nTotal $9.99",
        "expected": {"merchant": "AMAZON", "total": 9.99, "date": None, "items_count": 1},
    },
    {
        "name": "no_date_4",
        "text": "Boots\nShampoo 4.50\nToothpaste 3.00\nTotal £7.50",
        "expected": {"merchant": "Boots", "total": 7.50, "date": None, "items_count": 2},
    },
    {
        "name": "no_date_5",
        "text": "UBER\nTrip to Airport\nTotal £35.00",
        "expected": {"merchant": "UBER", "total": 35.00, "date": None, "items_count": 1},
    },
    # ── No items (5) ────────────────────────────────────────────────────
    {
        "name": "no_items_1",
        "text": "TESCO\n25/06/2026\nTotal £2.85",
        "expected": {"merchant": "TESCO", "total": 2.85, "date": "2026-06-25", "items_count": 0},
    },
    {
        "name": "no_items_2",
        "text": "PRET A MANGER\n08/07/2026\nTotal £8.20",
        "expected": {
            "merchant": "PRET A MANGER",
            "total": 8.20,
            "date": "2026-07-08",
            "items_count": 0,
        },
    },
    {
        "name": "no_items_3",
        "text": "AMAZON\n12/12/2026\nTotal $42.99",
        "expected": {"merchant": "AMAZON", "total": 42.99, "date": "2026-12-12", "items_count": 0},
    },
    {
        "name": "no_items_4",
        "text": "EE\n15/03/2026\nTotal £25.00",
        "expected": {"merchant": "EE", "total": 25.00, "date": "2026-03-15", "items_count": 0},
    },
    {
        "name": "no_items_5",
        "text": "Netflix\n01/04/2026\nTotal $15.99",
        "expected": {"merchant": "Netflix", "total": 15.99, "date": "2026-04-01", "items_count": 0},
    },
    # ── Multiple totals (5) ─────────────────────────────────────────────
    {
        "name": "multi_total_1",
        "text": "TESCO\n25/06/2026\nMilk 1.65\nSubtotal 1.65\nVAT 0.33\nTotal £1.98",
        "expected": {"merchant": "TESCO", "total": 1.98, "date": "2026-06-25", "items_count": 1},
    },
    {
        "name": "multi_total_2",
        "text": "IKEA\n10/03/2026\nTable 49.99\nChair 89.99\nSubtotal 139.98\nVAT 27.99\nGrand Total £167.97",
        "expected": {"merchant": "IKEA", "total": 167.97, "date": "2026-03-10", "items_count": 2},
    },
    {
        "name": "multi_total_3",
        "text": "Sainsbury's\n14/04/2026\nWine 12.00\nSubtotal 12.00\nTotal £12.00",
        "expected": {
            "merchant": "Sainsbury's",
            "total": 12.00,
            "date": "2026-04-14",
            "items_count": 1,
        },
    },
    {
        "name": "multi_total_4",
        "text": "Amazon\n22/05/2026\nBook 15.99\nSubtotal 15.99\nDelivery 0.00\nTotal $15.99",
        "expected": {"merchant": "Amazon", "total": 15.99, "date": "2026-05-22", "items_count": 1},
    },
    {
        "name": "multi_total_5",
        "text": "Costa Coffee\n07/09/2026\nLatte 4.20\nSubtotal 4.20\nTotal £4.20",
        "expected": {
            "merchant": "Costa Coffee",
            "total": 4.20,
            "date": "2026-09-07",
            "items_count": 1,
        },
    },
    # ── OCR errors / edge cases (5) ─────────────────────────────────────
    {
        "name": "ocr_typo_merchant",
        "text": "TESC0 STORES LTD\n25/06/2026\nMilk 1.65\nTotal £2.85",
        "expected": {
            "merchant": "TESC0 STORES LTD",
            "total": 2.85,
            "date": "2026-06-25",
            "items_count": 1,
        },
    },
    {
        "name": "ocr_garbled_numbers",
        "text": "TESCO\n25/06/2026\nMilk 1.6S\nBread 1.2O\nTotal £2.85",
        "expected": {"merchant": "TESCO", "total": 2.85, "date": "2026-06-25", "items_count": 0},
    },
    {
        "name": "ocr_no_spaces",
        "text": "TESCO\n25/06/2026\nMilk1.65\nBread1.20\nTotal£2.85",
        "expected": {"merchant": "TESCO", "total": 2.85, "date": "2026-06-25", "items_count": 2},
    },
    {
        "name": "receipt_with_discount",
        "text": "ZARA\n15/12/2026\nDress 59.99\nDiscount -10.00\nTotal €49.99",
        "expected": {"merchant": "ZARA", "total": 49.99, "date": "2026-12-15", "items_count": 2},
    },
    {
        "name": "receipt_tax_only",
        "text": "M&S Foodhall\n22/06/2026\nPrepared Meal 6.50\nVAT 1.30\nTotal £7.80",
        "expected": {
            "merchant": "M&S Foodhall",
            "total": 7.80,
            "date": "2026-06-22",
            "items_count": 1,
        },
    },
    # ── Extra edge cases (10) ───────────────────────────────────────────
    {
        "name": "uber_eats",
        "text": "Uber Eats\n28/02/2026\nPad Thai 12.00\nSpring Rolls 5.00\nDelivery Fee 2.50\nTotal £19.50",
        "expected": {
            "merchant": "Uber Eats",
            "total": 19.50,
            "date": "2026-02-28",
            "items_count": 3,
        },
    },
    {
        "name": "spotify_sub",
        "text": "SPOTIFY PREMIUM\n03/01/2026\nIndividual Plan\nTotal $11.99",
        "expected": {
            "merchant": "SPOTIFY PREMIUM",
            "total": 11.99,
            "date": "2026-01-03",
            "items_count": 1,
        },
    },
    {
        "name": "google_play",
        "text": "Google Play Store\n17/05/2026\nApp Purchase\nTotal $4.99",
        "expected": {
            "merchant": "Google Play Store",
            "total": 4.99,
            "date": "2026-05-17",
            "items_count": 1,
        },
    },
    {
        "name": "nike_store",
        "text": "Nike Store London\n08/06/2026\nRunning Shoes 120.00\nSocks 15.00\nTotal £135.00",
        "expected": {
            "merchant": "Nike Store London",
            "total": 135.00,
            "date": "2026-06-08",
            "items_count": 2,
        },
    },
    {
        "name": "hotel_bill",
        "text": "Premier Inn\n12/07/2026\nRoom Night 89.00\nBreakfast 12.50\nTotal £101.50",
        "expected": {
            "merchant": "Premier Inn",
            "total": 101.50,
            "date": "2026-07-12",
            "items_count": 2,
        },
    },
    {
        "name": "gym_membership",
        "text": "PureGym\n01/08/2026\nMonthly Membership\nTotal £29.99",
        "expected": {"merchant": "PureGym", "total": 29.99, "date": "2026-08-01", "items_count": 1},
    },
    {
        "name": "council_tax",
        "text": "Council Tax\n01/08/2026\nMonthly Payment\nTotal £185.00",
        "expected": {
            "merchant": "Council Tax",
            "total": 185.00,
            "date": "2026-08-01",
            "items_count": 1,
        },
    },
    {
        "name": "dentist_visit",
        "text": "Specsavers\n15/09/2026\nEye Test 25.00\nGlasses 149.00\nTotal £174.00",
        "expected": {
            "merchant": "Specsavers",
            "total": 174.00,
            "date": "2026-09-15",
            "items_count": 2,
        },
    },
    {
        "name": "cash_withdrawal",
        "text": "Barclays ATM\n20/10/2026\nCash Withdrawal\nTotal £50.00",
        "expected": {
            "merchant": "Barclays ATM",
            "total": 50.00,
            "date": "2026-10-20",
            "items_count": 1,
        },
    },
    {
        "name": "amazon_renewal",
        "text": "Amazon Prime\n15/11/2026\nAnnual Renewal\nTotal £95.00",
        "expected": {
            "merchant": "Amazon Prime",
            "total": 95.00,
            "date": "2026-11-15",
            "items_count": 1,
        },
    },
]


def get_eval_receipts() -> list[dict]:
    """Return a deep copy of the eval dataset."""
    return copy.deepcopy(EVAL_RECEIPTS)


def count_eval_receipts() -> int:  # noqa: E501
    """Return the total number of eval receipts."""
    return len(EVAL_RECEIPTS)
