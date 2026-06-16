#!/usr/bin/env python3
"""
Generic Special Procedures mandate ingestion pipeline.

Extends the corpus by adding all annual thematic reports from a single
mandate-holder office (Special Rapporteur / Independent Expert / Working
Group). Reuses the PDF→paragraphs converter from ingest_new_gcs.py and the
labelling patterns from quality_pipeline v6.

Usage:
    python3 ingest_sp_mandate.py --mandate disability       # ingest SR Disability
    python3 ingest_sp_mandate.py --list                     # list configured mandates

Adding a new mandate:
    1. Append a record to MANDATES below with:
        - committee_label   ("SR Disability", "SR Torture", …)
        - mandate_holders   list of (year_max, full_name)
        - reports           list of (year, signature, presented, subject_name)
    2. Run with --mandate <slug>.

The pipeline:
    1. For each report, download the English PDF via OHCHR Download.aspx.
    2. Extract paragraphs using PyMuPDF (same code as for GCs).
    3. Apply SP labelling patterns.
    4. Save labelled JSON in json_labeled_v2/ (corpus build dir).
    5. Append metadata records to specialprocedures_info.json.

Idempotent: skips reports already in the SP metadata. Run repeatedly without
duplication.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF — same dependency as ingest_new_gcs.py

ROOT = Path(__file__).resolve().parent
SP_META = ROOT / 'mysite_pythonanywhere' / 'specialprocedures_info.json'
SP_LABELED_DIR = ROOT / 'json_labeled_v2'
PDF_CACHE = ROOT / 'sp_ingest_pdfs'

# Same TLS/UA setup as the link validator. UN servers reject Python's default UA.
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

USER_AGENT = (
    'Mozilla/5.0 (compatible; GenevaReporter-SPIngest/1.0; '
    '+https://github.com/lszoszk/generalcomments)'
)


# ---------------------------------------------------------------------------
# Mandate registry. Add new mandates here.
# ---------------------------------------------------------------------------
MANDATES: dict[str, dict] = {
    'extreme-poverty': {
        'committee_label': 'SR Extreme Poverty',
        'full_name': 'Special Rapporteur on extreme poverty and human rights',
        # (year_max, name). Covers the Alston (2014–2020) + De Schutter
        # (2020–) era listed on OHCHR's annual-reports page. Pre-2014
        # reports (Sepúlveda et al., incl. the Guiding Principles
        # A/HRC/21/39) live on a separate "previous mandate-holders" page
        # and are not included here.
        # NB transition: A/75/181/Rev.1 (2020) is De Schutter's; the
        # year-only rule maps it to Alston — corrected post-ingest.
        'mandate_holders': [
            (2020, 'Philip Alston'),
            (9999, 'Olivier De Schutter'),
        ],
        # Catalogue from OHCHR's "Annual reports" page
        # https://www.ohchr.org/en/special-procedures/sr-poverty/annual-reports
        # Thematic reports only — addenda excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2026, 'A/HRC/62/42',    'HRC 62nd session', 'The manufacturing of poverty'),
            (2025, 'A/80/138',       'GA 80th session',  'Far-right populism and the future of social protection'),
            (2025, 'A/HRC/59/51',    'HRC 59th session', 'Weathering the storm: poverty, climate change and social protection'),
            (2024, 'A/79/162',       'GA 79th session',  'The burnout economy: poverty and mental health'),
            (2024, 'A/HRC/56/61',    'HRC 56th session', 'Eradicating poverty beyond growth'),
            (2023, 'A/78/175',       'GA 78th session',  'The working poor: a human rights approach to wages'),
            (2023, 'A/HRC/53/33',    'HRC 53rd session', 'The employment guarantee as a tool in the fight against poverty'),
            (2022, 'A/77/157',       'GA 77th session',  'Banning discrimination on grounds of socioeconomic disadvantage'),
            (2022, 'A/HRC/50/38',    'HRC 50th session', 'Non-take-up of rights in the context of social protection'),
            (2021, 'A/76/177',       'GA 76th session',  'Ending the vicious cycles of poverty'),
            (2021, 'A/HRC/47/36',    'HRC 47th session', 'Global Fund for Social Protection: international solidarity in the service of poverty eradication'),
            (2020, 'A/75/181/Rev.1', 'GA 75th session',  'The “just transition” in the economic recovery: eradicating poverty within planetary boundaries'),
            (2020, 'A/HRC/44/40',    'HRC 44th session', 'The parlous state of poverty eradication'),
            (2019, 'A/74/493',       'GA 74th session',  'Digital welfare states and human rights'),
            (2019, 'A/HRC/41/39',    'HRC 41st session', 'Climate change and poverty'),
            (2018, 'A/73/396',       'GA 73rd session',  'Privatization and human rights'),
            (2018, 'A/HRC/38/33',    'HRC 38th session', 'The role of the International Monetary Fund in relation to social protection'),
            (2017, 'A/72/502',       'GA 72nd session',  'The enjoyment of civil and political rights by persons living in poverty'),
            (2017, 'A/HRC/35/26',    'HRC 35th session', 'Universal basic income'),
            (2016, 'A/71/367',       'GA 71st session',  'United Nations responsibility for the cholera outbreak in Haiti'),
            (2016, 'A/HRC/32/31',    'HRC 32nd session', 'Marginalization of economic and social rights'),
            (2015, 'A/70/274',       'GA 70th session',  'The World Bank and human rights'),
            (2015, 'A/HRC/29/31',    'HRC 29th session', 'Extreme inequality and human rights'),
            (2014, 'A/69/297',       'GA 69th session',  'Implementation of the right to social protection through the adoption of social protection floors'),
        ],
    },
    'food': {
        'committee_label': 'SR Food',
        'full_name': 'Special Rapporteur on the right to food',
        # (year_max, name) — first row whose year_max >= report year.
        # Ziegler (2000–April 2008), De Schutter (May 2008–April 2014),
        # Elver (June 2014–April 2020), Fakhri (May 2020–April 2026).
        # NB transitions (year-only rule misattributes the handover doc):
        #   A/HRC/7/5  (2008) is Ziegler's final HRC report — rule → De Schutter
        #   A/69/275   (2014, GA) is Elver's — rule → De Schutter
        #   A/75/219   (2020, GA) is Fakhri's — rule → Elver
        # All three corrected post-ingest in specialprocedures_info.json
        # and docs/documents.json.
        'mandate_holders': [
            (2007, 'Jean Ziegler'),
            (2014, 'Olivier De Schutter'),
            (2020, 'Hilal Elver'),
            (9999, 'Michael Fakhri'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-food/annual-thematic-reports
        # Main thematic reports only — addenda (mission/communications),
        # corrigenda and country-visit docs excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2025, 'A/HRC/58/48',    'HRC 58th session', 'The right to food, finance and national action plans'),
            (2025, 'A/80/213',       'GA 80th session',  'Corporate power and human rights in food systems'),
            (2024, 'A/HRC/55/49',    'HRC 55th session', 'Fisheries and the right to food in the context of climate change'),
            (2024, 'A/79/171',       'GA 79th session',  'Starvation and the right to food, with an emphasis on the Palestinian people’s food sovereignty'),
            (2023, 'A/HRC/52/40',    'HRC 52nd session', 'Conflict and the right to food'),
            (2023, 'A/78/202',       'GA 78th session',  'Interim report of the Special Rapporteur on the right to food'),
            (2022, 'A/77/177',       'GA 77th session',  'Right to food and the COVID-19 pandemic'),
            (2022, 'A/HRC/49/43',    'HRC 49th session', 'Seeds, right to life and farmers’ rights'),
            (2021, 'A/76/237',       'GA 76th session',  'Food systems and human rights'),
            (2021, 'A/HRC/46/33',    'HRC 46th session', 'Vision of the Special Rapporteur on the right to food'),
            (2020, 'A/75/219',       'GA 75th session',  'The right to food in the context of international trade law and policy'),
            (2020, 'A/HRC/43/44',    'HRC 43rd session', 'Critical perspective on food systems, food crises and the future of the right to food'),
            (2019, 'A/74/164',       'GA 74th session',  'The Sustainable Development Goals and the right to food'),
            (2019, 'A/HRC/40/56',    'HRC 40th session', 'Fishery workers and the right to food'),
            (2018, 'A/73/164',       'GA 73rd session',  'Agricultural workers and the right to food'),
            (2018, 'A/HRC/37/61',    'HRC 37th session', 'The right to food in the context of natural disasters'),
            (2017, 'A/72/188',       'GA 72nd session',  'Interim report of the Special Rapporteur on the right to food'),
            (2017, 'A/HRC/34/48',    'HRC 34th session', 'Effects of pesticides on the right to food'),
            (2016, 'A/71/282',       'GA 71st session',  'The right to food and nutrition'),
            (2016, 'A/HRC/31/51',    'HRC 31st session', 'Integrating a gender perspective in the right to food'),
            (2015, 'A/70/287',       'GA 70th session',  'Impact of climate change on the right to food'),
            (2015, 'A/HRC/28/65',    'HRC 28th session', 'Access to justice and the right to food: the way forward'),
            (2014, 'A/69/275',       'GA 69th session',  'Report to the General Assembly on the right to food'),
            (2014, 'A/HRC/25/57',    'HRC 25th session', 'The transformative potential of the right to food'),
            (2013, 'A/68/288',       'GA 68th session',  'Assessing a decade of progress on the right to food'),
            (2013, 'A/HRC/22/50',    'HRC 22nd session', 'Women’s rights and the right to food'),
            (2012, 'A/67/268',       'GA 67th session',  'Fisheries and the right to food'),
            (2012, 'A/HRC/19/59',    'HRC 19th session', 'The right to an adequate diet: the agriculture-food-health nexus'),
            (2011, 'A/66/262',       'GA 66th session',  'Contract farming and other business models inclusive of small-scale farmers'),
            (2011, 'A/HRC/16/49',    'HRC 16th session', 'Agroecology and the right to food'),
            (2010, 'A/65/281',       'GA 65th session',  'Access to land and the right to food'),
            (2010, 'A/HRC/13/33',    'HRC 13th session', 'Agribusiness and the right to food'),
            (2009, 'A/64/170',       'GA 64th session',  'Seed policies and the right to food'),
            (2009, 'A/HRC/10/5',     'HRC 10th session', 'The role of development cooperation and food aid in realizing the right to adequate food'),
            (2008, 'A/63/278',       'GA 63rd session',  'Report to the General Assembly on the right to food'),
            (2008, 'A/HRC/9/23',     'HRC 9th session',  'Building resilience in response to the global food crisis'),
            (2008, 'A/HRC/7/5',      'HRC 7th session',  'The right to food and refugees from hunger'),
            (2007, 'A/62/289',       'GA 62nd session',  'The impact of biofuels on the right to food'),
            (2007, 'A/HRC/4/30',     'HRC 4th session',  'Children and their right to food'),
            (2006, 'E/CN.4/2006/44', 'CHR 62nd session', 'Defining the right to food in an era of globalization'),
            (2005, 'A/60/350',       'GA 60th session',  'The responsibilities of international organizations concerning the right to food'),
            (2005, 'E/CN.4/2005/47', 'CHR 61st session', 'Extraterritorial obligations of States to the right to food'),
            (2004, 'A/59/385',       'GA 59th session',  'The right to food and fishing livelihoods'),
            (2004, 'E/CN.4/2004/10', 'CHR 60th session', 'Food security and sovereignty'),
            (2003, 'A/58/330',       'GA 58th session',  'Transnational corporations and the right to food'),
            (2003, 'E/CN.4/2003/54', 'CHR 59th session', 'International guidelines on the right to food; water and the right to food'),
            (2002, 'A/57/356',       'GA 57th session',  'Access to land, agrarian reform and the right to food'),
            (2002, 'E/CN.4/2002/58', 'CHR 58th session', 'Justiciability of the right to food'),
            (2001, 'A/56/210',       'GA 56th session',  'Definition of the right to food'),
            (2001, 'E/CN.4/2001/53', 'CHR 57th session', 'Definition and history of the right to food'),
        ],
    },
    'water-sanitation': {
        'committee_label': 'SR Water and Sanitation',
        'full_name': 'Special Rapporteur on the human rights to safe drinking water and sanitation',
        # (year_max, name) — first row whose year_max >= report year.
        # Mandate created 2008 (Independent Expert); de Albuquerque became
        # Special Rapporteur in 2011. Holders: de Albuquerque (2008–Oct 2014),
        # Léo Heller (Nov 2014–Oct 2020), Pedro Arrojo-Agudo (Nov 2020–).
        # Both handovers fell in November, AFTER each year's GA/HRC reports
        # were presented, so the year-only rule needs no transition fixes.
        'mandate_holders': [
            (2014, 'Catarina de Albuquerque'),
            (2020, 'Léo Heller'),
            (9999, 'Pedro Arrojo-Agudo'),
        ],
        # Catalogue transcribed from OHCHR's "Annual reports" page
        # https://www.ohchr.org/en/special-procedures/sr-water-and-sanitation/annual-reports
        # Main thematic reports only — addenda (handbook/good-practices/
        # priorities), corrigenda, and the symbol-less multi-part climate-change
        # special report excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2025, 'A/80/117',    'GA 80th session',  'Democratic water governance under a human rights-based approach'),
            (2025, 'A/HRC/60/30', 'HRC 60th session', 'Water and energy nexus'),
            (2024, 'A/79/190',    'GA 79th session',  'The water/food nexus: a human rights perspective'),
            (2024, 'A/HRC/57/48', 'HRC 57th session', 'Water and economy nexus: managing water for productive uses from a human rights perspective'),
            (2023, 'A/78/253',    'GA 78th session',  'Water as an argument for peace, twinning and cooperation'),
            (2023, 'A/HRC/54/32', 'HRC 54th session', 'Fulfilling the human rights of those living in poverty and restoring the health of aquatic ecosystems'),
            (2022, 'A/77/167',    'GA 77th session',  'Human rights to safe drinking water and sanitation of people living in impoverished rural areas'),
            (2022, 'A/HRC/51/24', 'HRC 51st session', 'Human rights to safe drinking water and sanitation of indigenous peoples'),
            (2021, 'A/76/159',    'GA 76th session',  'Risks and impacts of the commodification and financialization of water on the human rights to water and sanitation'),
            (2021, 'A/HRC/48/50', 'HRC 48th session', 'Planning and vision for the mandate from 2020 to 2023'),
            (2020, 'A/75/208',    'GA 75th session',  'Human rights and the privatization of water and sanitation services'),
            (2020, 'A/HRC/45/10', 'HRC 45th session', 'Progressive realization of the human rights to water and sanitation'),
            (2020, 'A/HRC/45/11', 'HRC 45th session', 'Progress report on the human rights to water and sanitation (2010–2020)'),
            (2019, 'A/74/197',    'GA 74th session',  'Impact of megaprojects on the human rights to water and sanitation'),
            (2019, 'A/HRC/42/47', 'HRC 42nd session', 'Human rights to water and sanitation in spheres of life beyond the household, with an emphasis on public spaces'),
            (2018, 'A/73/162',    'GA 73rd session',  'The principle of accountability'),
            (2018, 'A/HRC/39/55', 'HRC 39th session', 'The human rights to water and sanitation of forcibly displaced persons'),
            (2017, 'A/72/127',    'GA 72nd session',  'Development cooperation and the human rights to water and sanitation'),
            (2017, 'A/HRC/36/45', 'HRC 36th session', 'Regulation of water and sanitation services'),
            (2016, 'A/71/302',    'GA 71st session',  'Development cooperation and the realization of the human rights to water and sanitation'),
            (2016, 'A/HRC/33/49', 'HRC 33rd session', 'Gender equality in the realization of the human rights to water and sanitation'),
            (2015, 'A/70/203',    'GA 70th session',  'Different levels and types of services and the human rights to water and sanitation'),
            (2015, 'A/HRC/30/39', 'HRC 30th session', 'Affordability of water and sanitation services'),
            (2014, 'A/69/213',    'GA 69th session',  'Participation in the realization of the human rights to water and sanitation'),
            (2014, 'A/HRC/27/55', 'HRC 27th session', 'Common violations of the human rights to water and sanitation'),
            (2013, 'A/68/264',    'GA 68th session',  'Wastewater management in the realization of the rights to water and sanitation'),
            (2013, 'A/HRC/24/44', 'HRC 24th session', 'Sustainability and non-retrogression in the realization of the rights to water and sanitation'),
            (2012, 'A/67/270',    'GA 67th session',  'Integrating non-discrimination and equality into the post-2015 development agenda for water, sanitation and hygiene'),
            (2012, 'A/HRC/21/42', 'HRC 21st session', 'Stigma and the realization of the human rights to water and sanitation'),
            (2011, 'A/66/255',    'GA 66th session',  'Financing for the realization of the rights to water and sanitation'),
            (2011, 'A/HRC/18/33', 'HRC 18th session', 'Planning for the realization of the rights to water and sanitation'),
            (2010, 'A/65/254',    'GA 65th session',  'The Millennium Development Goals and the human rights to water and sanitation'),
            (2010, 'A/HRC/15/31', 'HRC 15th session', 'Human rights obligations related to non-State service provision in water and sanitation'),
            (2009, 'A/HRC/12/24', 'HRC 12th session', 'Human rights obligations related to access to sanitation'),
            (2009, 'A/HRC/10/6',  'HRC 10th session', 'Preliminary report laying out the mandate work plan'),
        ],
    },
    'executions': {
        'committee_label': 'SR Executions',
        'full_name': 'Special Rapporteur on extrajudicial, summary or arbitrary executions',
        # (year_max, name) — first row whose year_max >= report year.
        # Alston (2004–July 2010), Heyns (Aug 2010–July 2016),
        # Callamard (Aug 2016–Mar 2021), Tidball-Binz (Apr 2021–).
        # NB transitions (GA report in the handover year belongs to the
        # successor; year-only rule misattributes it to the predecessor):
        #   A/65/321 (2010 GA) -> Heyns;  A/71/372 (2016 GA) -> Callamard;
        #   A/76/264 (2021 GA) -> Tidball-Binz.
        # (A/HRC/47/33 (2021) is Callamard's own farewell-reflection report,
        # correctly hers under the year rule.)
        'mandate_holders': [
            (2010, 'Philip Alston'),
            (2016, 'Christof Heyns'),
            (2021, 'Agnès Callamard'),
            (9999, 'Morris Tidball-Binz'),
        ],
        # Catalogue from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-executions/annual-thematic-reports
        # THEMATIC reports only (HRC + GA, 2007–2025). The pre-2007 CHR/GA
        # reports are general annual / country-situation reports, not
        # thematic-issue reports, and are excluded. Addenda (communications,
        # studies), corrigenda and the Khashoggi CRP annex excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2025, 'A/HRC/59/54', 'HRC 59th session', 'Rights of families of victims of unlawful killings'),
            (2025, 'A/80/214',    'GA 80th session',  'Investigation and prevention of unlawful killings by law enforcement officials'),
            (2024, 'A/HRC/56/56', 'HRC 56th session', 'Protection of the dead'),
            (2024, 'A/79/172',    'GA 79th session',  'Investigating and preventing unlawful deaths of LGBTIQ+ persons'),
            (2023, 'A/HRC/53/29', 'HRC 53rd session', 'Deaths in prisons'),
            (2023, 'A/78/254',    'GA 78th session',  'Investigation of femicide'),
            (2022, 'A/HRC/50/34', 'HRC 50th session', 'Medico-legal death investigations'),
            (2022, 'A/77/270',    'GA 77th session',  'Reflection on the fortieth anniversary of the mandate'),
            (2021, 'A/HRC/47/33', 'HRC 47th session', 'Reflection on five years of the mandate (Agnès Callamard)'),
            (2021, 'A/76/264',    'GA 76th session',  'Vision report'),
            (2020, 'A/HRC/44/38', 'HRC 44th session', 'Targeted killings through armed drones'),
            (2020, 'A/75/384',    'GA 75th session',  'The respectful and lawful handling of mass graves'),
            (2019, 'A/HRC/41/36', 'HRC 41st session', 'Investigation, accountability and prevention of intentional State killings of human rights defenders, journalists and dissidents'),
            (2019, 'A/74/318',    'GA 74th session',  'Application of the death penalty to foreign nationals and consular assistance'),
            (2018, 'A/HRC/38/44', 'HRC 38th session', 'Armed non-State actors and the protection of the right to life'),
            (2018, 'A/73/314',    'GA 73rd session',  'Saving lives is not a crime'),
            (2017, 'A/HRC/35/23', 'HRC 35th session', 'A gender-sensitive approach to arbitrary killings'),
            (2017, 'A/72/335',    'GA 72nd session',  'Unlawful death of refugees and migrants'),
            (2016, 'A/HRC/32/39', 'HRC 32nd session', 'The right to life and the use of force by private security providers in law enforcement'),
            (2016, 'A/HRC/31/66', 'HRC 31st session', 'Practical recommendations for the proper management of assemblies (joint report)'),
            (2016, 'A/71/372',    'GA 71st session',  'Review and update of issues considered between 2010 and 2016'),
            (2015, 'A/HRC/29/37', 'HRC 29th session', 'Use of information and communications technologies to secure the right to life'),
            (2015, 'A/70/304',    'GA 70th session',  'The role of forensic investigations in protecting the right to life; the death penalty and foreign nationals'),
            (2014, 'A/HRC/26/36', 'HRC 26th session', 'Protection of the right to life during law enforcement; armed drones and autonomous weapons systems'),
            (2014, 'A/69/265',    'GA 69th session',  'Regional human rights systems; less lethal and unmanned weapons in law enforcement'),
            (2013, 'A/HRC/23/47', 'HRC 23rd session', 'Lethal autonomous robotics and the protection of life'),
            (2013, 'A/68/382',    'GA 68th session',  'Armed drones and the right to life'),
            (2012, 'A/HRC/20/22', 'HRC 20th session', 'Protection of the right to life of journalists'),
            (2012, 'A/67/275',    'GA 67th session',  'Restrictions on the death penalty'),
            (2011, 'A/HRC/17/28', 'HRC 17th session', 'Protecting the right to life in the context of policing assemblies'),
            (2011, 'A/66/330',    'GA 66th session',  'Protection of the right to life in the context of arrests'),
            (2010, 'A/65/321',    'GA 65th session',  'New technologies and human rights fact-finding; targeted killings and accountability'),
            (2009, 'A/HRC/11/2',  'HRC 11th session', 'Reprisals; execution of juvenile offenders; the killing of "witches"; lethal force in policing assemblies'),
            (2009, 'A/64/187',    'GA 64th session',  'Vigilante killings and mob justice'),
            (2008, 'A/HRC/8/3',   'HRC 8th session',  'National commissions of inquiry; the right to seek pardon or commutation of a death sentence; prisoners running prisons'),
            (2008, 'A/63/313',    'GA 63rd session',  'Witness protection and ending impunity; making military justice systems human rights compatible'),
            (2007, 'A/HRC/4/20',  'HRC 4th session',  'The mandate in armed conflicts; the death penalty for the most serious crimes; the mandatory death penalty'),
        ],
    },
    'racism': {
        'committee_label': 'SR Racism',
        'full_name': 'Special Rapporteur on contemporary forms of racism, racial discrimination, xenophobia and related intolerance',
        # (year_max, name) — first row whose year_max >= report year.
        # Muigai (2008–Oct 2011), Ruteere (Nov 2011–Oct 2017),
        # Achiume (Nov 2017–Oct 2022), Ashwini K.P. (Nov 2022–). All
        # handovers fell in November, between the report years included
        # here, so no transition fixes are needed.
        'mandate_holders': [
            (2011, 'Githu Muigai'),
            (2017, 'Mutuma Ruteere'),
            (2022, 'E. Tendayi Achiume'),
            (9999, 'Ashwini K.P.'),
        ],
        # Catalogue from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-racism/annual-thematic-reports
        # The DISTINCT-THEME series (2012–2025 GA+HRC) plus the three
        # clearly thematic earlier reports (2009 poverty, 2010 conflict,
        # 2011 Roma/caste). The pre-2012 GA reports and pre-2009 CHR/HRC
        # reports are general "contemporary manifestations of racism"
        # surveys / activities reports (one is explicitly "without a
        # thematic component") and are excluded as non-thematic.
        # (year, signature, presented, subject)
        'reports': [
            (2025, 'A/80/496',    'GA 80th session',  'Conflict and racism, racial discrimination and xenophobia'),
            (2025, 'A/HRC/59/62', 'HRC 59th session', 'Intersectionality from a racial justice perspective'),
            (2024, 'A/79/316',    'GA 79th session',  'Special measures to achieve substantive racial equality'),
            (2024, 'A/HRC/56/68', 'HRC 56th session', 'Artificial intelligence and racial discrimination'),
            (2023, 'A/78/538',    'GA 78th session',  'Online racist hate speech'),
            (2023, 'A/HRC/53/60', 'HRC 53rd session', 'Strategic vision and priorities of the Special Rapporteur'),
            (2022, 'A/77/290',    'GA 77th session',  'Ecological crisis, climate change and systemic racism'),
            (2022, 'A/HRC/50/60', 'HRC 50th session', 'Racial justice and equality analysis of the 2030 Agenda and the Sustainable Development Goals'),
            (2021, 'A/76/434',    'GA 76th session',  'Twentieth anniversary of the Durban Declaration and Programme of Action'),
            (2021, 'A/HRC/48/76', 'HRC 48th session', 'Digital technologies and the xenophobic exclusion of migrants, refugees and stateless persons'),
            (2020, 'A/75/590',    'GA 75th session',  'Border and immigration enforcement and emerging digital technologies'),
            (2020, 'A/HRC/44/57', 'HRC 44th session', 'Racial discrimination in the design and use of emerging digital technologies'),
            (2019, 'A/74/321',    'GA 74th session',  'Reparations for racial discrimination rooted in slavery and colonialism'),
            (2019, 'A/HRC/41/54', 'HRC 41st session', 'Global extractivism and racial equality'),
            (2018, 'A/73/305',    'GA 73rd session',  'Nationalist populism and racial equality'),
            (2018, 'A/HRC/38/52', 'HRC 38th session', 'Racial discrimination in citizenship, nationality and immigration laws'),
            (2017, 'A/72/287',    'GA 72nd session',  'Combating racial discrimination and xenophobia in a counter-terrorism context'),
            (2017, 'A/HRC/35/41', 'HRC 35th session', 'Overview of the thematic work of the mandate; racism in a counter-terrorism context'),
            (2016, 'A/71/301',    'GA 71st session',  'The role of national human rights institutions and national action plans'),
            (2016, 'A/HRC/32/50', 'HRC 32nd session', 'Xenophobia: its conceptualization, trends and manifestations'),
            (2015, 'A/70/335',    'GA 70th session',  'Collection of disaggregated data to combat racial discrimination'),
            (2015, 'A/HRC/29/46', 'HRC 29th session', 'Racial and ethnic profiling in law enforcement'),
            (2014, 'A/69/340',    'GA 69th session',  'Racism in sport'),
            (2014, 'A/HRC/26/49', 'HRC 26th session', 'Manifestations of racism on the Internet and social media'),
            (2013, 'A/68/333',    'GA 68th session',  'Poverty and racism'),
            (2013, 'A/HRC/23/56', 'HRC 23rd session', 'The role of education in preventing racism'),
            (2012, 'A/67/326',    'GA 67th session',  'Racism and the Internet'),
            (2012, 'A/HRC/20/33', 'HRC 20th session', 'Prevention of racism in line with the Durban documents'),
            (2011, 'A/HRC/17/40', 'HRC 17th session', 'Racism against Roma and discrimination based on work and descent (caste)'),
            (2010, 'A/HRC/14/43', 'HRC 14th session', 'Racism, racial discrimination and xenophobia in situations of conflict'),
            (2009, 'A/HRC/11/36', 'HRC 11th session', 'Poverty and racism'),
        ],
    },
    'violence-against-women': {
        'committee_label': 'SR Violence against Women',
        'full_name': 'Special Rapporteur on violence against women and girls, its causes and consequences',
        # (year_max, name) — first row whose year_max >= report year.
        # NB transition years: A/70/209 (2015) is Šimonović's, A/76/132
        # (2021) is Alsalem's; year-only rule maps them to the predecessor —
        # corrected in specialprocedures_info.json post-ingest.
        'mandate_holders': [
            (2003, 'Radhika Coomaraswamy'),
            (2009, 'Yakin Ertürk'),
            (2015, 'Rashida Manjoo'),
            (2021, 'Dubravka Šimonović'),
            (9999, 'Reem Alsalem'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-violence-against-women/annual-thematic-reports
        # Main thematic reports only — addenda (communications/mission/summary),
        # corrigenda and country-situation docs excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2025, 'A/HRC/59/47',   'HRC 59th session', 'Sex-based violence against women and girls: new frontiers and emerging issues'),
            (2025, 'A/80/158',      'GA 80th session',  'The different manifestations of violence against women and girls in the context of surrogacy'),
            (2024, 'A/HRC/56/48',   'HRC 56th session', 'Prostitution and violence against women and girls'),
            (2024, 'A/79/325',      'GA 79th session',  'Violence against women and girls in sport'),
            (2023, 'A/HRC/53/36',   'HRC 53rd session', 'Custody, violence against women and violence against children'),
            (2023, 'A/78/256',      'GA 78th session',  'Violence against women and girls, nationality laws and statelessness'),
            (2022, 'A/HRC/50/26',   'HRC 50th session', 'Violence against indigenous women and girls'),
            (2022, 'A/77/136',      'GA 77th session',  'Violence against women and girls in the context of the climate crisis'),
            (2021, 'A/HRC/47/26',   'HRC 47th session', 'Rape as a grave and systematic human rights violation and manifestation of gender-based violence, and its prevention'),
            (2021, 'A/76/132',      'GA 76th session',  'Taking stock of the femicide watch initiative'),
            (2020, 'A/HRC/44/52',   'HRC 44th session', 'Violence against women journalists'),
            (2020, 'A/75/144',      'GA 75th session',  'Intersection between the COVID-19 pandemic and the pandemic of gender-based violence, with a focus on domestic violence'),
            (2019, 'A/HRC/41/42',   'HRC 41st session', 'Twenty-five years of the mandate: an analysis of its evolution, current challenges and the way forward'),
            (2019, 'A/74/137',      'GA 74th session',  'A human rights-based approach to mistreatment and violence against women in reproductive health services, with a focus on obstetric violence'),
            (2018, 'A/HRC/38/47',   'HRC 38th session', 'Online violence against women and girls'),
            (2018, 'A/73/301',      'GA 73rd session',  'Violence against women in politics'),
            (2017, 'A/HRC/35/30',   'HRC 35th session', 'A human rights-based approach to integrated services and protection measures, with a focus on shelters and protection orders'),
            (2017, 'A/72/134',      'GA 72nd session',  'Adequacy of the international legal framework on violence against women'),
            (2016, 'A/HRC/32/42',   'HRC 32nd session', 'Vision-setting report of the Special Rapporteur'),
            (2016, 'A/71/398',      'GA 71st session',  'Modalities for the establishment of femicides/gender-related killings watch'),
            (2015, 'A/HRC/29/27',   'HRC 29th session', 'Existing legal standards and practices regarding violence against women in three regional human rights systems'),
            (2015, 'A/70/209',      'GA 70th session',  'Closing the gap in international human rights law: lessons from three regional human rights systems'),
            (2014, 'A/HRC/26/38',   'HRC 26th session', 'Violence against women: twenty years of developments to combat violence against women'),
            (2014, 'A/69/368',      'GA 69th session',  'Violence against women as a barrier to the effective realization of all human rights'),
            (2013, 'A/HRC/23/49',   'HRC 23rd session', 'State responsibility for eliminating violence against women'),
            (2013, 'A/68/340',      'GA 68th session',  'Pathways to, conditions and consequences of incarceration for women'),
            (2012, 'A/HRC/20/16',   'HRC 20th session', 'Gender-related killings of women'),
            (2012, 'A/67/227',      'GA 67th session',  'Violence against women with disabilities'),
            (2011, 'A/HRC/17/26',   'HRC 17th session', 'Multiple and intersecting forms of discrimination and violence against women'),
            (2011, 'A/66/215',      'GA 66th session',  'Continuum of violence against women from the home to the transnational sphere'),
            (2010, 'A/HRC/14/22',   'HRC 14th session', 'Reparations to women who have been subjected to violence'),
            (2009, 'A/HRC/11/6',    'HRC 11th session', 'Political economy of women’s human rights'),
            (2008, 'A/HRC/7/6',     'HRC 7th session',  'Indicators on violence against women and State response'),
            (2007, 'A/HRC/4/34',    'HRC 4th session',  'Intersections between culture and violence against women'),
            (2006, 'E/CN.4/2006/61', 'CHR 62nd session', 'The due diligence standard as a tool for the elimination of violence against women'),
            (2005, 'E/CN.4/2005/72', 'CHR 61st session', 'Intersections of violence against women and HIV/AIDS'),
            (2004, 'E/CN.4/2004/66', 'CHR 60th session', 'Towards an effective implementation of international norms to end violence against women'),
            (2003, 'E/CN.4/2003/75', 'CHR 59th session', 'Integration of the human rights of women and the gender perspective'),
            (2002, 'E/CN.4/2002/83', 'CHR 58th session', 'Cultural practices in the family that constitute violence towards women'),
            (2001, 'E/CN.4/2001/73', 'CHR 57th session', 'Violence against women perpetrated or condoned by the State during times of armed conflict'),
            (2000, 'E/CN.4/2000/68', 'CHR 56th session', 'Trafficking in women, women’s migration and violence against women'),
            (1999, 'E/CN.4/1999/68', 'CHR 55th session', 'Violence against women in the family'),
            (1998, 'E/CN.4/1998/54', 'CHR 54th session', 'Violence perpetrated or condoned by the State, including violence in times of armed conflict'),
            (1997, 'E/CN.4/1997/47', 'CHR 53rd session', 'Violence in the community: sexual violence, trafficking in women and women migrant workers'),
            (1996, 'E/CN.4/1996/53', 'CHR 52nd session', 'Violence in the family and domestic violence'),
            (1995, 'E/CN.4/1995/42', 'CHR 51st session', 'Preliminary report of the Special Rapporteur on violence against women'),
        ],
    },
    'trafficking': {
        'committee_label': 'SR Trafficking',
        'full_name': 'Special Rapporteur on trafficking in persons, especially women and children',
        # (year_max, name) — first row whose year_max >= report year.
        # NB transition years: A/69/269 (2014) is Giammarinaro's, A/75/169
        # (2020) is Mullally's; year-only rule maps them to the predecessor —
        # corrected in specialprocedures_info.json post-ingest.
        'mandate_holders': [
            (2008, 'Sigma Huda'),
            (2014, 'Joy Ngozi Ezeilo'),
            (2020, 'Maria Grazia Giammarinaro'),
            (9999, 'Siobhán Mullally'),
        ],
        # Catalogue transcribed from OHCHR's "Annual reports" page
        # https://www.ohchr.org/en/special-procedures/sr-trafficking-in-persons/annual-reports
        # Thematic reports only — consultation/meeting addenda excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2025, 'A/80/166',      'GA 80th session',  'Child rights and child trafficking in conflict situations'),
            (2025, 'A/HRC/59/56',  'HRC 59th session', 'Migrant domestic workers and trafficking in persons: prevention, rights protection and access to justice'),
            (2024, 'A/79/161',      'GA 79th session',  'Trafficking in persons and gender and peace and security'),
            (2024, 'A/HRC/56/60',  'HRC 56th session', 'Trafficking in persons, mixed migration and protection at sea'),
            (2023, 'A/78/172',      'GA 78th session',  'Strengthening accountability for trafficking in persons in conflict situations'),
            (2023, 'A/HRC/53/28',  'HRC 53rd session', 'Refugee protection, internal displacement and statelessness'),
            (2022, 'A/77/170',      'GA 77th session',  'Gender dimensions of trafficking in persons in the context of climate change, displacement and disaster risk reduction'),
            (2022, 'A/HRC/50/33',  'HRC 50th session', 'Trafficking in persons in the agriculture sector: human rights due diligence and sustainable development'),
            (2021, 'A/76/263',      'GA 76th session',  'Intersections between trafficking in persons and terrorism'),
            (2021, 'A/HRC/47/34',  'HRC 47th session', 'Implementation of the non-punishment principle'),
            (2020, 'A/75/169',      'GA 75th session',  'Twenty years after: implementing and going beyond the Palermo Protocol towards a human rights-centred approach'),
            (2020, 'A/HRC/44/45',  'HRC 44th session', 'Beyond law enforcement, towards social justice: an effective human rights-based approach to trafficking'),
            (2019, 'A/74/189',      'GA 74th session',  'Access to remedy for victims of trafficking for abuses committed by businesses and their suppliers'),
            (2019, 'A/HRC/41/46',  'HRC 41st session', 'Innovative and transformative models of social inclusion of survivors of trafficking'),
            (2018, 'A/73/171',      'GA 73rd session',  'Gender dimension of trafficking in conflict and post-conflict settings (women, peace and security agenda)'),
            (2018, 'A/HRC/38/45',  'HRC 38th session', 'Early identification, referral and protection of victims of trafficking in mixed migration movements'),
            (2017, 'A/72/164',      'GA 72nd session',  'Joint study on the vulnerabilities of children to sale, trafficking and other forms of exploitation in conflict and humanitarian crisis'),
            (2017, 'A/HRC/35/37',  'HRC 35th session', 'Strengthening voluntary standards for businesses on preventing and combating trafficking and labour exploitation in supply chains'),
            (2016, 'A/71/303',      'GA 71st session',  'Trafficking in persons in conflict and post-conflict situations'),
            (2016, 'A/HRC/32/41',  'HRC 32nd session', 'Trafficking in persons in conflict and post-conflict situations: protecting victims and people at risk'),
            (2015, 'A/70/260',      'GA 70th session',  'Due diligence and trafficking in persons'),
            (2015, 'A/HRC/29/38',  'HRC 29th session', 'Agenda setting of the work of the Special Rapporteur'),
            (2014, 'A/69/269',      'GA 69th session',  'The first decade of the mandate; Basic Principles on the right to an effective remedy for victims of trafficking'),
            (2014, 'A/HRC/26/37',  'HRC 26th session', 'Stocktaking exercise on the work of the mandate on its tenth anniversary'),
            (2013, 'A/68/256',      'GA 68th session',  'Trafficking in persons for the removal of organs'),
            (2013, 'A/HRC/23/48',  'HRC 23rd session', 'Integration of a human rights-based approach in measures to discourage the demand that fosters exploitation'),
            (2012, 'A/67/261',      'GA 67th session',  'Human trafficking in supply chains'),
            (2012, 'A/HRC/20/18',  'HRC 20th session', 'A human rights-based approach to the administration of criminal justice in cases of trafficking'),
            (2011, 'A/66/283',      'GA 66th session',  'The right to an effective remedy for trafficked persons'),
            (2011, 'A/HRC/17/35',  'HRC 17th session', 'The right to an effective remedy for trafficked persons'),
            (2010, 'A/65/288',      'GA 65th session',  'Prevention of trafficking in persons'),
            (2010, 'A/HRC/14/32',  'HRC 14th session', 'Regional and subregional cooperation in promoting a human rights-based approach to combating trafficking'),
            (2009, 'A/64/290',      'GA 64th session',  'Identification, protection of and assistance to victims of trafficking'),
            (2009, 'A/HRC/10/16',  'HRC 10th session', 'Mandate of the Special Rapporteur on trafficking in persons'),
            (2007, 'A/HRC/4/23',   'HRC 4th session',  'Forced marriage in the context of trafficking in persons'),
            (2006, 'E/CN.4/2006/62','CHR 62nd session', 'Demand for commercial sexual exploitation and trafficking'),
            (2005, 'E/CN.4/2005/71','CHR 61st session', 'Mandate of the Special Rapporteur on trafficking in persons'),
        ],
    },
    'environment': {
        'committee_label': 'SR Environment',
        'full_name': 'Special Rapporteur on the human right to a clean, healthy and sustainable environment',
        # (year_max, name) — first row whose year_max >= report year.
        # NB transition years: A/73/188 (2018) is Boyd's, A/79/270 (2024) is
        # Puentes Riaño's; the year-only rule maps them to the predecessor —
        # corrected in specialprocedures_info.json post-ingest.
        'mandate_holders': [
            (2018, 'John H. Knox'),
            (2024, 'David R. Boyd'),
            (9999, 'Astrid Puentes Riaño'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-environment/annual-thematic-reports
        # Substantive thematic reports only — expert-seminar/meeting summaries
        # and call-for-inputs notes excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2026, 'A/HRC/61/47', 'HRC 61st session', 'Priority actions towards breathing clean air, protecting public health and ensuring a healthy environment'),
            (2025, 'A/80/187',     'GA 80th session',  'Framework for environmental, social and human rights impact assessments and the right to a clean, healthy and sustainable environment'),
            (2025, 'A/HRC/58/59', 'HRC 58th session', 'The ocean and human rights'),
            (2024, 'A/79/270',     'GA 79th session',  'Overview of the implementation of the human right to a clean, healthy and sustainable environment'),
            (2024, 'A/HRC/55/43', 'HRC 55th session', 'Business, planetary boundaries, and the right to a clean, healthy and sustainable environment'),
            (2023, 'A/78/168',     'GA 78th session',  'Paying polluters: the catastrophic consequences of investor-State dispute settlement for climate and environment action and human rights'),
            (2023, 'A/HRC/52/33', 'HRC 52nd session', 'Women, girls and the right to a clean, healthy and sustainable environment'),
            (2022, 'A/77/284',     'GA 77th session',  'The human right to a clean, healthy and sustainable environment: a catalyst for accelerated action to achieve the Sustainable Development Goals'),
            (2022, 'A/HRC/49/53', 'HRC 49th session', 'Non-toxic environment to live, work, study and play'),
            (2021, 'A/76/179',     'GA 76th session',  'Healthy and sustainable food: reducing the environmental impacts of food systems on human rights'),
            (2021, 'A/HRC/46/28', 'HRC 46th session', 'Human rights and the global water crisis: water pollution, water scarcity and water-related disasters'),
            (2020, 'A/75/161',     'GA 75th session',  'A healthy biosphere and the right to a healthy environment'),
            (2019, 'A/74/161',     'GA 74th session',  'Safe climate'),
            (2019, 'A/HRC/40/55', 'HRC 40th session', 'Clean air and the right to a healthy and sustainable environment'),
            (2018, 'A/73/188',     'GA 73rd session',  'Global recognition of the right to a safe, clean, healthy and sustainable environment'),
            (2018, 'A/HRC/37/58', 'HRC 37th session', 'Children’s rights and the environment'),
            (2018, 'A/HRC/37/59', 'HRC 37th session', 'Framework principles on human rights and the environment'),
            (2017, 'A/HRC/34/49', 'HRC 34th session', 'Biodiversity and human rights'),
            (2016, 'A/HRC/31/52', 'HRC 31st session', 'Climate change and human rights'),
            (2016, 'A/HRC/31/53', 'HRC 31st session', 'Implementation report on human rights obligations relating to the environment'),
            (2015, 'A/HRC/28/61', 'HRC 28th session', 'Good practices in the use of human rights obligations relating to the environment'),
            (2014, 'A/HRC/25/53', 'HRC 25th session', 'Mapping report on human rights obligations relating to the enjoyment of a safe, clean, healthy and sustainable environment'),
            (2013, 'A/HRC/22/43', 'HRC 22nd session', 'Preliminary report of the Independent Expert on human rights and the environment'),
        ],
    },
    'migrants': {
        'committee_label': 'SR Migrants',
        'full_name': 'Special Rapporteur on the human rights of migrants',
        # (year_max, name) — pick the first row whose year_max >= report year.
        # NB: transition-year reports map to the predecessor by this year-only
        # rule; corrected in specialprocedures_info.json post-ingest.
        'mandate_holders': [
            (2005, 'Gabriela Rodríguez Pizarro'),
            (2011, 'Jorge Bustamante'),
            (2017, 'François Crépeau'),
            (2023, 'Felipe González Morales'),
            (9999, 'Gehad Madi'),
        ],
        # Catalogue transcribed from OHCHR's "Annual reports" page
        # https://www.ohchr.org/en/special-procedures/sr-migrants/annual-reports
        # Thematic reports only — communications reports, CRPs and addenda excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2025, 'A/80/302',       'GA 80th session',  'Externalization of migration governance and its effect on the human rights of migrants'),
            (2025, 'A/HRC/59/49',    'HRC 59th session', 'Phenomenon of migrants going missing or subjected to enforced disappearance: a human rights analysis'),
            (2024, 'A/79/213',       'GA 79th session',  'Children are children first and foremost: protecting child rights in migration contexts'),
            (2024, 'A/HRC/56/54',    'HRC 56th session', 'Revisiting migrants’ contributions with a human rights-based approach'),
            (2023, 'A/78/180',       'GA 78th session',  'Protection of the labour and human rights of migrant workers'),
            (2023, 'A/HRC/53/26',    'HRC 53rd session', 'How to expand and diversify regularization mechanisms and programmes to enhance the protection of the human rights of migrants'),
            (2022, 'A/77/189',       'GA 77th session',  'The impact of climate change on the human rights of migrants'),
            (2022, 'A/HRC/50/31',    'HRC 50th session', 'Human rights violations at international borders: trends, prevention and accountability'),
            (2021, 'A/76/257',       'GA 76th session',  'Impact of COVID-19 on the human rights of migrants'),
            (2021, 'A/HRC/47/30',    'HRC 47th session', 'Means to address the human rights impact of pushbacks of migrants on land and at sea'),
            (2020, 'A/75/183',       'GA 75th session',  'Ending immigration detention of children and providing adequate care and reception for them'),
            (2020, 'A/HRC/44/42',    'HRC 44th session', 'Right to freedom of association of migrants and their defenders'),
            (2019, 'A/74/191',       'GA 74th session',  'Good practices and initiatives on gender-responsive migration legislation and policies'),
            (2019, 'A/HRC/41/38',    'HRC 41st session', 'Impact of migration on migrant women and girls: a gender perspective'),
            (2018, 'A/73/178/Rev.1', 'GA 73rd session',  'Access to justice for migrant persons'),
            (2018, 'A/HRC/38/41',    'HRC 38th session', 'Return and reintegration of migrants'),
            (2017, 'A/72/173',       'GA 72nd session',  '2035 agenda for facilitating human mobility'),
            (2017, 'A/HRC/35/25',    'HRC 35th session', '2035 agenda for facilitating human mobility'),
            (2016, 'A/71/285',       'GA 71st session',  'Developing the global compact on migration'),
            (2016, 'A/HRC/32/40',    'HRC 32nd session', 'Impact of bilateral and multilateral trade agreements on the human rights of migrants'),
            (2015, 'A/70/310',       'GA 70th session',  'Recruitment practices and the human rights of migrants'),
            (2015, 'A/HRC/29/36',    'HRC 29th session', 'Follow-up to the regional study on the management of the external borders of the European Union and its impact on the human rights of migrants'),
            (2014, 'A/69/302',       'GA 69th session',  'Human rights of migrants in the post-2015 development agenda'),
            (2014, 'A/HRC/26/35',    'HRC 26th session', 'Labour exploitation of migrants'),
            (2013, 'A/68/283',       'GA 68th session',  'Global migration governance'),
            (2013, 'A/HRC/23/46',    'HRC 23rd session', 'Regional study: management of the external borders of the European Union and its impact on the human rights of migrants'),
            (2012, 'A/67/299',       'GA 67th session',  'Climate change and migration'),
            (2012, 'A/HRC/20/24',    'HRC 20th session', 'Detention of migrants in an irregular situation'),
            (2011, 'A/66/264',       'GA 66th session',  'Overview of the activities of the mandate'),
            (2011, 'A/HRC/17/33',    'HRC 17th session', 'Recapitulation of main thematic issues: irregular migration, protection of children, and the right to housing and health of migrants'),
            (2010, 'A/65/222',       'GA 65th session',  'Impact of the criminalization of migration on the protection and enjoyment of human rights'),
            (2010, 'A/HRC/14/30',    'HRC 14th session', 'Enjoyment of the rights to health and adequate housing by migrants'),
            (2009, 'A/64/213',       'GA 64th session',  'The protection of children in the context of migration'),
            (2009, 'A/HRC/11/7',     'HRC 11th session', 'Protection of children in the context of migration'),
            (2008, 'A/HRC/7/12',     'HRC 7th session',  'Criminalization of irregular migration'),
            (2007, 'A/62/218',       'GA 62nd session',  'Border control, expulsion, and conditions for the admission and stay of migrants'),
            (2006, 'A/61/324',       'GA 61st session',  'Impact of certain laws and administrative measures on migrants'),
            (2006, 'E/CN.4/2006/73',  'CHR 62nd session', 'Overview of the activities of the mandate'),
            (2005, 'A/60/357',       'GA 60th session',  'Preliminary observations regarding migration and the human rights of migrants'),
            (2005, 'E/CN.4/2005/85',  'CHR 61st session', 'Racism, racial discrimination and xenophobia; migrant women and unaccompanied children'),
            (2004, 'A/59/377',       'GA 59th session',  'Overview of the activities of the mandate'),
            (2004, 'E/CN.4/2004/76',  'CHR 60th session', 'Vulnerability of migrant domestic workers'),
            (2003, 'A/58/275',       'GA 58th session',  'Good practices observed by the Special Rapporteur'),
            (2003, 'E/CN.4/2003/85',  'CHR 59th session', 'Human rights of migrants deprived of their liberty'),
            (2002, 'A/57/292',       'GA 57th session',  'Conceptual and substantive development of the question of the human rights of migrants'),
            (2002, 'E/CN.4/2002/94',  'CHR 58th session', 'Overview of the activities of the mandate'),
            (2001, 'E/CN.4/2001/83',  'CHR 57th session', 'Overview of the activities of the mandate'),
            (2000, 'E/CN.4/2000/82',  'CHR 56th session', 'Overview of the activities of the mandate'),
        ],
    },
    'housing': {
        'committee_label': 'SR Adequate Housing',
        'full_name': 'Special Rapporteur on adequate housing as a component of the right to an adequate standard of living, and on the right to non-discrimination in this context',
        # (year_max, name) — pick the first row whose year_max >= report year.
        # NB: transition-year reports A/63/275 (2008, Rolnik), A/69/274 (2014,
        # Farha) and A/75/148 (2020, Rajagopal) map to the predecessor by this
        # year-only rule; corrected in specialprocedures_info.json post-ingest.
        'mandate_holders': [
            (2008, 'Miloon Kothari'),
            (2014, 'Raquel Rolnik'),
            (2020, 'Leilani Farha'),
            (9999, 'Balakrishnan Rajagopal'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-housing/annual-thematic-reports
        # Thematic reports only — country/mission addenda, communications
        # reports and corrigenda excluded.
        # (year, signature, presented, subject)
        'reports': [
            (2026, 'A/HRC/61/43',       'HRC 61st session', 'Guiding Principles on Resettlement'),
            (2025, 'A/80/351',          'GA 80th session',  'Land and the right to adequate housing'),
            (2025, 'A/HRC/58/50',       'HRC 58th session', 'Towards a just approach to the global housing crisis and migrants'),
            (2024, 'A/79/317',          'GA 79th session',  'Towards guiding principles on resettlement: a review and assessment of current laws, policies and practices'),
            (2024, 'A/HRC/56/61/Add.3', 'HRC 56th session', 'Breaking the cycle: ending the criminalization of homelessness and poverty'),
            (2024, 'A/HRC/55/53',       'HRC 55th session', 'Resettlement after eviction and displacement: addressing a human rights crisis'),
            (2023, 'A/78/192',          'GA 78th session',  'A place to live in dignity for all: make housing affordable'),
            (2023, 'A/HRC/52/28',       'HRC 52nd session', 'Towards a just transformation: climate crisis and the right to housing'),
            (2022, 'A/77/190',          'GA 77th session',  'The right to adequate housing during violent conflict'),
            (2022, 'A/HRC/49/48',       'HRC 49th session', 'Spatial segregation and the right to adequate housing'),
            (2021, 'A/76/408',          'GA 76th session',  'Discrimination in the context of housing'),
            (2021, 'A/HRC/47/43',       'HRC 47th session', 'Twenty years of the mandate: taking stock, moving forward'),
            (2020, 'A/75/148',          'GA 75th session',  'COVID-19 and the right to adequate housing'),
            (2020, 'A/HRC/43/43',       'HRC 43rd session', 'Guidelines for the implementation of the right to adequate housing'),
            (2019, 'A/74/183',          'GA 74th session',  'The right to housing for indigenous peoples'),
            (2019, 'A/HRC/40/61',       'HRC 40th session', 'Access to justice for the right to housing'),
            (2018, 'A/73/310/Rev.1',    'GA 73rd session',  'The right to housing for residents of informal settlements'),
            (2018, 'A/HRC/37/53',       'HRC 37th session', 'Human rights-based national housing strategies'),
            (2017, 'A/72/128',          'GA 72nd session',  'The right to adequate housing of persons with disabilities'),
            (2017, 'A/HRC/34/51',       'HRC 34th session', 'Financialization of housing and the right to adequate housing'),
            (2016, 'A/71/310',          'GA 71st session',  'The right to life and the right to adequate housing: indivisibility and interdependence'),
            (2016, 'A/HRC/31/54',       'HRC 31st session', 'Homelessness as a global human rights crisis that demands an urgent global response'),
            (2015, 'A/70/270',          'GA 70th session',  'Centrality of the right to adequate housing for the New Urban Agenda'),
            (2015, 'A/HRC/28/62',       'HRC 28th session', 'Responsibilities of local and other subnational governments in relation to the right to adequate housing'),
            (2014, 'A/69/274',          'GA 69th session',  'Preliminary thoughts and priority areas of work of the new mandate-holder'),
            (2014, 'A/HRC/25/54',       'HRC 25th session', 'Guiding principles on security of tenure for the urban poor'),
            (2013, 'A/68/289',          'GA 68th session',  'Analysis of two alternative housing policies: rental and collective housing'),
            (2013, 'A/HRC/22/46',       'HRC 22nd session', 'Mapping and framing security of tenure'),
            (2012, 'A/67/286',          'GA 67th session',  'The impact of housing finance policies on the right to adequate housing of those living in poverty'),
            (2012, 'A/HRC/19/53',       'HRC 19th session', 'Women and their right to adequate housing'),
            (2011, 'A/66/270',          'GA 66th session',  'The right to adequate housing in disaster relief efforts'),
            (2011, 'A/HRC/16/42',       'HRC 16th session', 'Post-conflict and post-disaster reconstruction and the right to adequate housing'),
            (2010, 'A/65/261',          'GA 65th session',  'Migration and the right to adequate housing'),
            (2010, 'A/HRC/13/20',       'HRC 13th session', 'The impact of mega-events on the realization of the right to adequate housing'),
            (2009, 'A/64/255',          'GA 64th session',  'Climate change and the right to adequate housing'),
            (2009, 'A/HRC/10/7',        'HRC 10th session', 'The financial crisis and its causes'),
            (2008, 'A/63/275',          'GA 63rd session',  'Areas of work in the coming years and justiciability of the right to adequate housing'),
            (2008, 'A/HRC/7/16',        'HRC 7th session',  'Overview of the work of the first Special Rapporteur on the right to adequate housing'),
            (2007, 'A/HRC/4/18',        'HRC 5th session',  'Basic principles and guidelines on development-based evictions and displacement'),
            (2006, 'E/CN.4/2006/41',    'CHR 62nd session', 'The right to housing and the indivisibility of human rights'),
            (2005, 'E/CN.4/2005/48',    'CHR 61st session', 'Homelessness'),
            (2004, 'E/CN.4/2004/48',    'CHR 60th session', 'Forced evictions'),
            (2003, 'E/CN.4/2003/5',     'CHR 59th session', 'Emerging issues including water and indicators'),
            (2002, 'E/CN.4/2002/59',    'CHR 58th session', 'Discrimination and the impact of globalization'),
            (2001, 'E/CN.4/2001/51',    'CHR 57th session', 'Definition of the mandate and objectives'),
        ],
    },
    'disability': {
        'committee_label': 'SR Disability',
        'full_name': 'Special Rapporteur on the rights of persons with disabilities',
        # (year_max, name) — pick the first row whose year_max >= report year
        'mandate_holders': [
            (2020, 'Catalina Devandas-Aguilar'),
            (2023, 'Gerard Quinn'),
            (9999, 'Heba Hagrass'),
        ],
        # Catalog scraped from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-disability/annual-thematic-reports
        # (year, signature, presented, subject)
        'reports': [
            (2026, 'A/HRC/61/26', 'HRC 61st session', 'Equal participation of persons with disabilities in political life'),
            (2025, 'A/80/170',     'GA 80th session',  'Care and support for children with disabilities within the family environment and its gendered dimensions'),
            (2025, 'A/HRC/58/56',  'HRC 58th session', 'Thirty years of implementation of the Beijing Declaration and Platform for Action: its potential for women and girls with disabilities'),
            (2024, 'A/79/179',     'GA 79th session',  'Including people with disabilities in the review of the 2030 Agenda for Sustainable Development'),
            (2024, 'A/HRC/55/56',  'HRC 55th session', 'Taking stock of the first 10 years of the mandate and vision of the Special Rapporteur on the rights of persons with disabilities, Heba Hagrass'),
            (2023, 'A/78/174',     'GA 78th session',  'Peacebuilding and the inclusion of persons with disabilities'),
            (2023, 'A/HRC/52/32',  'HRC 52nd session', 'Transformation of services for persons with disabilities'),
            (2022, 'A/77/203',     'GA 77th session',  'Protection of the rights of persons with disabilities in the context of military operations'),
            (2022, 'A/HRC/49/52',  'HRC 49th session', 'Artificial intelligence and the rights of persons with disabilities'),
            (2021, 'A/76/146',     'GA 76th session',  'The rights of persons with disabilities in the context of armed conflict'),
            (2021, 'A/HRC/46/27',  'HRC 46th session', 'Vision report of the Special Rapporteur on the rights of persons with disabilities, Gerard Quinn'),
            (2020, 'A/75/186',     'GA 75th session',  'Disability-inclusive international cooperation'),
            (2020, 'A/HRC/43/41',  'HRC 43rd session', 'The impact of ableism in medical and scientific practice'),
            (2019, 'A/74/186',     'GA 74th session',  'Older persons with disabilities'),
            (2019, 'A/HRC/40/54',  'HRC 40th session', 'Deprivation of liberty of persons with disabilities'),
            (2018, 'A/73/161',     'GA 73rd session',  'Right to health of persons with disabilities'),
            (2018, 'A/HRC/37/56',  'HRC 37th session', 'Legal capacity and supported decision-making'),
            (2017, 'A/72/133',     'GA 72nd session',  'Sexual and reproductive health and rights of girls and young women with disabilities'),
            (2017, 'A/HRC/34/58',  'HRC 34th session', 'Access to rights-based support for persons with disabilities'),
            (2016, 'A/71/314',     'GA 71st session',  'Disability-inclusive policies'),
            (2016, 'A/HRC/31/62',  'HRC 31st session', 'The right of persons with disabilities to participate in decision-making'),
            (2015, 'A/70/297',     'GA 70th session',  'The right of persons with disabilities to social protection'),
            (2015, 'A/HRC/28/58',  'HRC 28th session', 'Vision report of the Special Rapporteur on the rights of persons with disabilities, Catalina Devandas-Aguilar'),
        ],
    },
    'health': {
        'committee_label': 'SR Health',
        'full_name': 'Special Rapporteur on the right of everyone to the enjoyment of the highest attainable standard of physical and mental health',
        'mandate_holders': [
            (2008, 'Paul Hunt'),
            (2014, 'Anand Grover'),
            (2020, 'Dainius Pūras'),
            (9999, 'Tlaleng Mofokeng'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports" page:
        # https://www.ohchr.org/en/special-procedures/sr-health/annual-thematic-reports
        # Thematic reports only — communications reports + addenda (Add.1,
        # Corr.1) excluded. Pre-2007 reports went to the Commission on
        # Human Rights (E/CN.4 symbols); the UN ODS serves those too.
        'reports': [
            (2025, 'A/80/184',      'GA 80th session',  'Health and care workers: the oath takers and defenders of the right to health'),
            (2025, 'A/HRC/59/48',   'HRC 59th session', 'Health and care workers as defenders of the right to health'),
            (2024, 'A/79/177',      'GA 79th session',  'Harm reduction for sustainable peace and development'),
            (2024, 'A/HRC/56/52',   'HRC 56th session', 'Drug use, harm reduction and the right to health'),
            (2023, 'A/78/185',      'GA 78th session',  'Food, nutrition and the right to health'),
            (2023, 'A/HRC/53/65',   'HRC 53rd session', 'Digital innovation, technologies and the right to health'),
            (2022, 'A/77/197',      'GA 77th session',  'Racism and the right to health'),
            (2022, 'A/HRC/50/28',   'HRC 50th session', 'Violence and its impact on the right to health'),
            (2021, 'A/76/172',      'GA 76th session',  'Sexual and reproductive health rights: challenges and opportunities during COVID-19'),
            (2021, 'A/HRC/47/28',   'HRC 47th session', 'Strategic priorities of work'),
            (2020, 'A/75/163',      'GA 75th session',  'Commentary on the COVID-19 pandemic'),
            (2020, 'A/HRC/44/48',   'HRC 44th session', 'Mental health and human rights: setting a rights-based global agenda'),
            (2019, 'A/74/174',      'GA 74th session',  'A human rights-based approach to health workforce education'),
            (2019, 'A/HRC/41/34',   'HRC 41st session', 'The role of the determinants of health in advancing the right to mental health'),
            (2018, 'A/73/216',      'GA 73rd session',  'Right to mental health of people on the move'),
            (2018, 'A/HRC/38/36',   'HRC 38th session', 'Deprivation of liberty and the right to health'),
            (2017, 'A/72/137',      'GA 72nd session',  'Corruption and the right to health'),
            (2017, 'A/HRC/35/21',   'HRC 35th session', 'The right to mental health'),
            (2016, 'A/71/304',      'GA 71st session',  'The right to health and the 2030 Agenda for Sustainable Development'),
            (2016, 'A/HRC/32/32',   'HRC 32nd session', 'The right to health of adolescents'),
            (2016, 'A/HRC/32/33',   'HRC 32nd session', 'Sport and healthy lifestyles as contributing factors to the right to health'),
            (2015, 'A/70/213',      'GA 70th session',  'The right to health in early childhood'),
            (2015, 'A/HRC/29/33',   'HRC 29th session', 'Work of the mandate and priorities of the Special Rapporteur'),
            (2014, 'A/69/299',      'GA 69th session',  'Implementation of the right to health framework'),
            (2014, 'A/HRC/26/31',   'HRC 26th session', 'Unhealthy foods and non-communicable diseases'),
            (2013, 'A/68/297',      'GA 68th session',  'The right to health in conflict situations'),
            (2013, 'A/HRC/23/41',   'HRC 23rd session', "Migrant workers' right to health"),
            (2013, 'A/HRC/23/42',   'HRC 23rd session', 'Access to medicines in the context of the right to health'),
            (2012, 'A/67/302',      'GA 67th session',  'Health financing in the context of the right to health'),
            (2012, 'A/HRC/20/15',   'HRC 20th session', 'Occupational health and the right to health'),
            (2011, 'A/66/254',      'GA 66th session',  'Criminalization of sexual and reproductive health'),
            (2011, 'A/HRC/18/37',   'HRC 18th session', 'The right to health of older persons'),
            (2011, 'A/HRC/17/43',   'HRC 17th session', 'Expert consultation on access to medicines'),
            (2011, 'A/HRC/17/25',   'HRC 17th session', 'The right to health and development'),
            (2010, 'A/65/255',      'GA 65th session',  'The right to health and international drug control'),
            (2010, 'A/HRC/14/20',   'HRC 14th session', 'Criminalization, the right to health and sexual orientation'),
            (2009, 'A/64/272',      'GA 64th session',  'The right to health and informed consent'),
            (2009, 'A/HRC/11/12',   'HRC 11th session', 'Access to medicines and intellectual property rights'),
            (2008, 'A/63/263',      'GA 63rd session',  'Annual report to the General Assembly (2008)'),
            (2008, 'A/HRC/7/11',    'HRC 7th session',  'Health systems and the right to the highest attainable standard of health'),
            (2007, 'A/62/214',      'GA 62nd session',  'Water, sanitation and the right to the highest attainable standard of health'),
            (2007, 'A/HRC/4/28',    'HRC 4th session',  'The health and human rights movement'),
            (2006, 'A/61/338',      'GA 61st session',  'The right to health and the reduction of maternal mortality'),
            (2006, 'E/CN.4/2006/48', 'Commission on Human Rights 2006', 'A human rights-based approach to health indicators'),
            (2005, 'A/60/348',      'GA 60th session',  'Health professionals and human rights education'),
            (2005, 'E/CN.4/2005/51', 'Commission on Human Rights 2005', 'Mental disability and the right to health'),
            (2004, 'A/59/422',      'GA 59th session',  'Health-related Millennium Development Goals'),
            (2004, 'E/CN.4/2004/49', 'Commission on Human Rights 2004', 'The right to sexual and reproductive health'),
            (2003, 'A/58/427',      'GA 58th session',  'Right to health indicators'),
            (2003, 'E/CN.4/2003/58', 'Commission on Human Rights 2003', 'Defining the human right to health'),
        ],
    },
    'education': {
        'committee_label': 'SR Education',
        'full_name': 'Special Rapporteur on the right to education',
        'mandate_holders': [
            (2004, 'Katarina Tomaševski'),
            (2010, 'Vernor Muñoz Villalobos'),
            (2016, 'Kishore Singh'),
            (2022, 'Koumbou Boly Barry'),
            (9999, 'Farida Shaheed'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports" page:
        # https://www.ohchr.org/en/special-procedures/sr-education/annual-thematic-reports
        # Thematic reports only — communications reports + addenda (Add.1,
        # Corr.1, CRP.2) excluded. Pre-2007 reports went to the Commission
        # on Human Rights (E/CN.4 symbols). A/HRC/20/21 and A/HRC/17/29 are
        # dated by their HRC session (20th = 2012, 17th = 2011); the OHCHR
        # page mislabels their calendar year.
        'reports': [
            (2025, 'A/80/479',      'GA 80th session',  'Right to education in armed conflict: a human rights imperative'),
            (2025, 'A/HRC/59/41',   'HRC 59th session', 'The right to be safe in education'),
            (2024, 'A/79/520',      'GA 79th session',  'Artificial intelligence in education'),
            (2024, 'A/HRC/56/58',   'HRC 56th session', 'The right to academic freedom'),
            (2023, 'A/78/364',      'GA 78th session',  'Role and rights of teachers'),
            (2023, 'A/HRC/53/27',   'HRC 53rd session', 'Securing the right to education: advances and critical challenges'),
            (2022, 'A/77/324',      'GA 77th session',  'Early childhood care and education'),
            (2022, 'A/HRC/50/32',   'HRC 50th session', 'Impact of the digitalization of education on the right to education'),
            (2021, 'A/76/158',      'GA 76th session',  'The right to education of migrants'),
            (2021, 'A/HRC/47/32',   'HRC 47th session', 'The cultural dimensions of the right to education'),
            (2020, 'A/75/178',      'GA 75th session',  'Interrelations between the right to education and the rights to water and sanitation'),
            (2020, 'A/HRC/44/39',   'HRC 44th session', 'Impact of the COVID-19 crisis on the right to education'),
            (2019, 'A/74/243',      'GA 74th session',  'Right to education and the prevention of atrocity crimes and mass or grave violations of human rights'),
            (2019, 'A/HRC/41/37',   'HRC 41st session', 'The right to education and Sustainable Development Goal 4 amid the growth of private actors in education'),
            (2018, 'A/73/262',      'GA 73rd session',  'The right to education for refugees'),
            (2018, 'A/HRC/38/32',   'HRC 38th session', 'Governance and the right to education'),
            (2017, 'A/72/496',      'GA 72nd session',  'Inclusion, equity and the right to education'),
            (2017, 'A/HRC/35/24',   'HRC 35th session', 'Realizing the right to education through non-formal education'),
            (2016, 'A/71/358',      'GA 71st session',  'Lifelong learning and the right to education'),
            (2016, 'A/HRC/32/37',   'HRC 32nd session', 'Issues and challenges to the right to education in the digital age'),
            (2015, 'A/70/342',      'GA 70th session',  'Public-private partnerships and the right to education'),
            (2015, 'A/HRC/29/30',   'HRC 29th session', 'Protecting education against commercialization'),
            (2014, 'A/69/402',      'GA 69th session',  'Privatization and the right to education'),
            (2014, 'A/HRC/26/27',   'HRC 26th session', 'Assessment of the educational attainment of students'),
            (2013, 'A/68/294',      'GA 68th session',  'The post-2015 education agenda'),
            (2013, 'A/HRC/23/35',   'HRC 23rd session', 'Justiciability and the right to education'),
            (2012, 'A/67/310',      'GA 67th session',  'Technical and vocational education and training'),
            (2012, 'A/HRC/20/21',   'HRC 20th session', 'Normative action for quality education'),
            (2011, 'A/66/269',      'GA 66th session',  'Financing education and update on education in emergencies'),
            (2011, 'A/HRC/17/29',   'HRC 17th session', 'Equality of opportunity in education'),
            (2010, 'A/65/162',      'GA 65th session',  'Sexual education'),
            (2010, 'A/HRC/14/25',   'HRC 14th session', 'The right to education of migrants, refugees and asylum-seekers'),
            (2009, 'A/HRC/11/8',    'HRC 11th session', 'The right to education of persons in detention'),
            (2008, 'A/HRC/8/10',    'HRC 8th session',  'Right to education in emergency situations'),
            (2007, 'A/HRC/4/29',    'HRC 4th session',  'The right to education of persons with disabilities'),
            (2006, 'E/CN.4/2006/45', 'Commission on Human Rights 2006', "Girls' right to education"),
            (2005, 'E/CN.4/2005/50', 'Commission on Human Rights 2005', 'Annual report (2005)'),
            (2004, 'E/CN.4/2004/45', 'Commission on Human Rights 2004', 'Annual report (2004)'),
            (2003, 'E/CN.4/2003/9',  'Commission on Human Rights 2003', 'Annual report (2003)'),
            (2002, 'E/CN.4/2002/60', 'Commission on Human Rights 2002', 'Annual report (2002)'),
            (2001, 'E/CN.4/2001/52', 'Commission on Human Rights 2001', 'Annual report (2001)'),
            (2000, 'E/CN.4/2000/6',  'Commission on Human Rights 2000', "The '4 As' framework — progress report"),
            (1999, 'E/CN.4/1999/49', 'Commission on Human Rights 1999', 'Preliminary report'),
        ],
    },
    'torture': {
        'committee_label': 'SR Torture',
        'full_name': 'Special Rapporteur on torture and other cruel, inhuman or degrading treatment or punishment',
        'mandate_holders': [
            (1993, 'Pieter Kooijmans'),
            (2001, 'Nigel S. Rodley'),
            (2004, 'Theo van Boven'),
            (2010, 'Manfred Nowak'),
            (2016, 'Juan E. Méndez'),
            (2022, 'Nils Melzer'),
            (9999, 'Alice Jill Edwards'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports"
        # page: ohchr.org/en/special-procedures/sr-torture/
        #       annual-thematic-reports-special-rapporteur
        # Annual thematic + activities reports only — communications
        # reports and country-visit addenda (Add.N) excluded. The
        # mandate is the oldest SP (1985); pre-2007 reports went to the
        # Commission on Human Rights (E/CN.4 symbols). Some 1980s-90s
        # symbols may not resolve on documents.un.org — the ingester
        # logs and skips those.
        'reports': [
            (2026, 'A/HRC/61/42',   'HRC 61st session', 'Charter of Rights of Victims and Survivors of Torture'),
            (2025, 'A/80/137',      'GA 80th session',  'Trends and developments in the global struggle to end torture'),
            (2025, 'A/HRC/58/55',   'HRC 58th session', 'Hostage-taking as torture'),
            (2024, 'A/79/181',      'GA 79th session',  'Investigating, prosecuting and preventing wartime sexual torture'),
            (2024, 'A/HRC/55/52',   'HRC 55th session', 'Current issues and good practices in prison management'),
            (2023, 'A/78/324',      'GA 78th session',  'Global trade in weapons and equipment used by law enforcement capable of inflicting torture'),
            (2023, 'A/HRC/52/30',   'HRC 52nd session', 'Good practices in criminalization, investigation, prosecution and sentencing for torture'),
            (2022, 'A/77/502',      'GA 77th session',  'Vision report of the Special Rapporteur on torture'),
            (2022, 'A/HRC/49/50',   'HRC 49th session', 'Impact of thematic reports'),
            (2021, 'A/76/168',      'GA 76th session',  'Accountability for torture and other cruel, inhuman or degrading treatment'),
            (2021, 'A/HRC/46/26',   'HRC 46th session', "Effectiveness of States' responses and follow-up to communications and visit requests"),
            (2020, 'A/75/179',      'GA 75th session',  'Biopsychosocial factors conducive to torture'),
            (2020, 'A/HRC/43/49',   'HRC 43rd session', 'Psychological torture'),
            (2019, 'A/74/148',      'GA 74th session',  'The prohibition of torture and ill-treatment in the context of domestic violence'),
            (2019, 'A/HRC/40/59',   'HRC 40th session', 'Corruption-related torture and ill-treatment'),
            (2018, 'A/73/207',      'GA 73rd session',  'Seventieth anniversary of the Universal Declaration of Human Rights'),
            (2018, 'A/HRC/37/50',   'HRC 37th session', 'Migration-related torture and other cruel, inhuman or degrading treatment'),
            (2017, 'A/72/178',      'GA 72nd session',  'Extra-custodial use of force and the prohibition of torture'),
            (2017, 'A/HRC/34/54',   'HRC 34th session', 'Thematic priorities of the Special Rapporteur (Nils Melzer)'),
            (2016, 'A/71/298',      'GA 71st session',  'Universal protocol for interviews'),
            (2016, 'A/HRC/31/57',   'HRC 31st session', 'Gender perspectives on torture'),
            (2015, 'A/70/303',      'GA 70th session',  'Extraterritorial application of the prohibition of torture'),
            (2015, 'A/HRC/28/68',   'HRC 28th session', 'Torture and ill-treatment of children deprived of their liberty'),
            (2014, 'A/69/387',      'GA 69th session',  'Role of forensic and medical sciences in the investigation and prevention of torture'),
            (2014, 'A/HRC/25/60',   'HRC 25th session', 'Use of information tainted by torture and the exclusionary rule'),
            (2013, 'A/68/295',      'GA 68th session',  'Review of the Standard Minimum Rules for the Treatment of Prisoners (Nelson Mandela Rules)'),
            (2013, 'A/HRC/22/53',   'HRC 22nd session', 'Torture and ill-treatment in healthcare settings'),
            (2012, 'A/67/279',      'GA 67th session',  'The death penalty and the prohibition of torture'),
            (2012, 'A/HRC/19/61',   'HRC 19th session', 'Commissions of inquiry into torture and other forms of ill-treatment'),
            (2011, 'A/66/268',      'GA 66th session',  'Solitary confinement'),
            (2011, 'A/HRC/16/52',   'HRC 16th session', 'Thematic priorities and methodology of work of the Special Rapporteur (Juan Méndez)'),
            (2010, 'A/65/273',      'GA 65th session',  'Impunity, rehabilitation centres and national preventive mechanisms'),
            (2010, 'A/HRC/13/39',   'HRC 13th session', 'Mandate and State cooperation; definition of torture and ill-treatment; non-refoulement'),
            (2009, 'A/64/215',      'GA 64th session',  'Conditions of detention and children in detention'),
            (2009, 'A/HRC/10/44',   'HRC 10th session', 'The death penalty and a human rights-based approach to drug policies'),
            (2008, 'A/63/175',      'GA 63rd session',  'Protecting persons with disabilities from torture; solitary confinement'),
            (2008, 'A/HRC/7/3',     'HRC 7th session',  'Strengthening the protection of women from torture'),
            (2007, 'A/62/221',      'GA 62nd session',  'Forensic expertise and avoiding deprivation of liberty to prevent torture'),
            (2007, 'A/HRC/4/33',    'HRC 4th session',  'Universal jurisdiction; remedy and reparation for victims of torture'),
            (2006, 'A/61/259',      'GA 61st session',  'Non-admissibility of evidence extracted by torture; entry into force of OPCAT'),
            (2006, 'E/CN.4/2006/6', 'Commission on Human Rights 2006', 'Diplomatic assurances; distinction between torture and other ill-treatment'),
            (2005, 'A/60/316',      'GA 60th session',  'Corporal punishment; non-refoulement and diplomatic assurances'),
            (2005, 'E/CN.4/2005/62', 'Commission on Human Rights 2005', 'Trade and production of equipment designed to inflict torture'),
            (2004, 'A/59/324',      'GA 59th session',  'The absolute prohibition of torture; non-refoulement; impact of torture on victims'),
            (2004, 'E/CN.4/2004/56', 'Commission on Human Rights 2004', 'Guarantees for persons deprived of liberty; HIV/AIDS and torture'),
            (2003, 'A/58/120',      'GA 58th session',  'Torture and anti-terrorism measures; reparation; psychiatric institutions'),
            (2003, 'E/CN.4/2003/68', 'Commission on Human Rights 2003', 'Methods of work of the Special Rapporteur'),
            (2003, 'E/CN.4/2003/69', 'Commission on Human Rights 2003', 'Trade in and production of equipment designed to inflict torture'),
            (2002, 'A/57/173',      'GA 57th session',  'Torture and anti-terrorism measures; visits to places of detention; corporal punishment of children'),
            (2002, 'E/CN.4/2002/137', 'Commission on Human Rights 2002', 'Initial report of Theo van Boven — methods of work'),
            (2002, 'E/CN.4/2002/76', 'Commission on Human Rights 2002', 'Final report of Nigel Rodley — general recommendations'),
            (2001, 'A/56/156',      'GA 56th session',  'Issues of concern: intimidation, enforced disappearance, impunity'),
            (2001, 'E/CN.4/2001/66', 'Commission on Human Rights 2001', 'Activities report (2001)'),
            (2000, 'A/55/290',      'GA 55th session',  'Issues of concern: gender, children, human rights defenders, torture and poverty'),
            (2000, 'E/CN.4/2000/9', 'Commission on Human Rights 2000', 'Activities report (2000)'),
            (1999, 'A/54/426',      'GA 54th session',  'First report to the General Assembly — overview of the mandate'),
            (1999, 'E/CN.4/1999/61', 'Commission on Human Rights 1999', 'Activities report (1999)'),
            (1998, 'E/CN.4/1998/38', 'Commission on Human Rights 1998', 'Activities report (1998)'),
            (1997, 'E/CN.4/1997/7',  'Commission on Human Rights 1997', 'Activities report (1997)'),
            (1996, 'E/CN.4/1996/35', 'Commission on Human Rights 1996', 'Activities report (1996)'),
            (1995, 'E/CN.4/1995/34', 'Commission on Human Rights 1995', 'Activities report (1995)'),
            (1994, 'E/CN.4/1994/31', 'Commission on Human Rights 1994', 'Activities report (1994)'),
            (1993, 'E/CN.4/1993/26', 'Commission on Human Rights 1993', 'Activities report (1993)'),
            (1992, 'E/CN.4/1992/17', 'Commission on Human Rights 1992', 'Activities report (1992)'),
            (1991, 'E/CN.4/1991/17', 'Commission on Human Rights 1991', 'Activities report (1991)'),
            (1990, 'E/CN.4/1990/17', 'Commission on Human Rights 1990', 'Activities report (1990)'),
            (1989, 'E/CN.4/1989/15', 'Commission on Human Rights 1989', 'Activities report (1989)'),
            (1988, 'E/CN.4/1988/17', 'Commission on Human Rights 1988', 'Activities report (1988)'),
            (1986, 'E/CN.4/1986/15', 'Commission on Human Rights 1986', 'Activities report (1986)'),
        ],
    },
    'indigenous': {
        'committee_label': 'SR Indigenous Peoples',
        'full_name': 'Special Rapporteur on the rights of indigenous peoples',
        'mandate_holders': [
            (2007, 'Rodolfo Stavenhagen'),
            (2013, 'James Anaya'),
            (2019, 'Victoria Tauli-Corpuz'),
            (9999, 'José Francisco Calí Tzay'),
        ],
        # Catalogue transcribed from OHCHR's "Annual thematic reports"
        # page: ohchr.org/en/special-procedures/sr-indigenous-peoples/
        #       annual-thematic-reports
        # HRC + GA thematic reports + the pre-2007 Commission on Human
        # Rights reports. Communications-observation addenda (Add.N)
        # excluded. No GA report for 2008 or 2010 (none was issued).
        'reports': [
            (2025, 'A/HRC/60/29',   'HRC 60th session', 'Recognition of Indigenous Peoples'),
            (2024, 'A/HRC/57/47',   'HRC 57th session', 'Indigenous persons with disabilities'),
            (2023, 'A/HRC/54/31',   'HRC 54th session', 'Green financing: a just transition to protect the rights of Indigenous Peoples'),
            (2022, 'A/HRC/51/28',   'HRC 51st session', 'Indigenous women and scientific and technical knowledge'),
            (2021, 'A/HRC/48/54',   'HRC 48th session', 'Indigenous peoples and COVID-19 recovery'),
            (2020, 'A/HRC/45/34',   'HRC 45th session', 'Mandate impacts and observations on consultation processes'),
            (2019, 'A/HRC/42/37',   'HRC 42nd session', 'Access to justice in ordinary and indigenous justice systems'),
            (2018, 'A/HRC/39/17',   'HRC 39th session', 'Attacks and criminalization of indigenous human rights defenders'),
            (2017, 'A/HRC/36/46',   'HRC 36th session', "Impacts of climate change and climate finance on indigenous peoples' rights"),
            (2016, 'A/HRC/33/42',   'HRC 33rd session', "International investment agreements and indigenous peoples' rights"),
            (2015, 'A/HRC/30/41',   'HRC 30th session', 'Rights of indigenous women and girls'),
            (2014, 'A/HRC/27/52',   'HRC 27th session', "Obstacles to the realization of indigenous peoples' rights"),
            (2013, 'A/HRC/24/41',   'HRC 24th session', 'Extractive industries and indigenous peoples'),
            (2012, 'A/HRC/21/47',   'HRC 21st session', 'Annual report on the rights of indigenous peoples (2012)'),
            (2011, 'A/HRC/18/35',   'HRC 18th session', 'Extractive industries operating within or near indigenous territories'),
            (2010, 'A/HRC/15/37',   'HRC 15th session', 'The situation of human rights and fundamental freedoms of indigenous people'),
            (2009, 'A/HRC/12/34',   'HRC 12th session', 'The duty of States to consult with indigenous peoples'),
            (2008, 'A/HRC/9/9',     'HRC 9th session',  'The United Nations Declaration on the Rights of Indigenous Peoples: implementation'),
            (2007, 'A/HRC/4/32',    'HRC 4th session',  'Recent trends concerning the rights of indigenous peoples'),
            (2025, 'A/80/181',      'GA 80th session',  "Identification, demarcation, registration and titling of Indigenous Peoples' lands"),
            (2024, 'A/79/160',      'GA 79th session',  'Mobile Indigenous Peoples'),
            (2023, 'A/78/162',      'GA 78th session',  'Tourism and the rights of Indigenous Peoples'),
            (2022, 'A/77/238',      'GA 77th session',  "Protected areas and indigenous peoples' rights"),
            (2021, 'A/76/202',      'GA 76th session',  'The rights of indigenous peoples living in urban areas'),
            (2020, 'A/75/185',      'GA 75th session',  'The impact of COVID-19 on the rights of indigenous peoples'),
            (2019, 'A/74/149',      'GA 74th session',  'The right of indigenous peoples to autonomy or self-government'),
            (2018, 'A/73/176',      'GA 73rd session',  'Indigenous peoples and self-governance'),
            (2017, 'A/72/186',      'GA 72nd session',  'Assessment of the implementation of the UN Declaration on the Rights of Indigenous Peoples'),
            (2016, 'A/71/229',      'GA 71st session',  "Conservation measures and their impact on indigenous peoples' rights"),
            (2015, 'A/70/301',      'GA 70th session',  'Impact of international investment and free trade on the human rights of indigenous peoples'),
            (2014, 'A/69/267',      'GA 69th session',  'Economic, social and cultural rights of indigenous peoples in the post-2015 development framework'),
            (2013, 'A/68/317',      'GA 68th session',  'Challenges to implement the UN Declaration on the Rights of Indigenous Peoples'),
            (2012, 'A/67/301',      'GA 67th session',  'Harmonizing activities affecting indigenous peoples within the United Nations system'),
            (2011, 'A/66/288',      'GA 66th session',  'Activities of the mandate and thematic issues examined'),
            (2009, 'A/64/338',      'GA 64th session',  "The Second International Decade of the World's Indigenous People"),
            (2007, 'A/62/286',      'GA 62nd session',  'Situation of the rights of indigenous peoples in Asia'),
            (2006, 'A/61/490',      'GA 61st session',  'Remarks on the UN Declaration on the Rights of Indigenous Peoples'),
            (2005, 'A/60/358',      'GA 60th session',  'Major human rights problems affecting indigenous peoples: poverty, education and armed conflict'),
            (2004, 'A/59/258',      'GA 59th session',  'Progress and major human rights problems affecting indigenous peoples'),
            (2006, 'E/CN.4/2006/78', 'Commission on Human Rights 2006', 'Implementation of norms concerning the rights of indigenous peoples'),
            (2005, 'E/CN.4/2005/88', 'Commission on Human Rights 2005', 'Indigenous peoples and education systems'),
            (2004, 'E/CN.4/2004/80', 'Commission on Human Rights 2004', 'Administration of justice, indigenous peoples and human rights'),
            (2003, 'E/CN.4/2003/90', 'Commission on Human Rights 2003', 'The impact of large-scale development projects on the human rights of indigenous peoples'),
            (2002, 'E/CN.4/2002/97', 'Commission on Human Rights 2002', 'International norms regarding the rights of indigenous peoples'),
        ],
    },
    # Future mandates go here (SR Food, SR Housing, …)
}


# ---------------------------------------------------------------------------
# SP labelling patterns. Same set as quality_pipeline v6, applied to each
# extracted paragraph.
# ---------------------------------------------------------------------------
LABEL_PATTERNS = [
    ('Children', [
        r'\bchild(?:ren)?\b', r'\bjuvenile\b', r'\binfant\b', r'\bnewborn\b',
        r'\bminors?\b', r'\bunder.?18\b', r'\bpediatric\b',
        r'\bchild marriage\b', r'\bchild\s+labor(?:ur)?\b', r'\bchild soldier\b',
    ]),
    ('Women/girls', [
        r'\bwom(?:an|en)\b', r'\bgirls?\b', r'\bfemale\b', r'\bmaternal\b',
        r'\bpregnan', r'\bmaternity\b', r'\bmothers?\b', r'\bwidow\b',
        r'\bgender.based violence\b', r'\bgender equality\b',
        r'\bFGM\b', r'\bfemale genital\b', r'\bsexual and reproductive\b',
        r'\bdomestic violence\b', r'\btraffick(?:ing|ed)', r'\bsexual exploit',
    ]),
    ('Persons with disabilities', [
        r'\bdisabilit(?:y|ies)\b', r'\bhandicap\b', r'\bimpairment\b',
        r'\bmental(?:ly)?\s+(?:ill\b|disorder\b|illness\b|health condition)',
        r'\bpsychiatric\b', r'\bcognitive disab\b', r'\bintellectual disab\b',
        r'\breason(?:able)? accommodat', r'\bdeaf(?:ness)?\b',
        r'\bblind(?:ness)?\b', r'\bwheelchair\b', r'\bmental health\b',
    ]),
    ('Migrants', [
        r'\bmigrant\b', r'\bimmigrant\b', r'\blabou?r migration\b',
        r'\bforeign worker\b', r'\bremittance\b',
        r'\bundocumented (?:person|worker|migrant)\b', r'\birregular migra\b',
        r'\bxenophobia\b',
    ]),
    ('Indigenous peoples', [
        r'\bindigenous (?:people|communit|right|land|culture|knowledge|group|person|woman|child)\b',
        r'\btribal (?:people|communit|right|land)\b',
        r'\bfree,?\s*prior\s*and\s*informed\s*consent\b', r'\bFPIC\b',
    ]),
    ('Persons deprived of their liberty', [
        r'\bprison(?:ers?|s)\b', r'\bdetain(?:ee|ment|ed\s+person)\b',
        r'\bincarcerat', r'\bimprison', r'\bjail(?:ed)?\b', r'\bremand(?:ed)?\b',
        r'\bconvict(?:ed|s)\b', r'\bplaces of detention\b',
        r'\bpersons? deprived of (?:their|his|her) liberty\b',
    ]),
    ('Refugees & asylum-seekers', [
        r'\brefugee\b', r'\basylum.seeker\b', r'\basylum seeker\b',
        r'\bnon-refoulement\b', r'\bpersecution\b',
    ]),
    ('Adolescents', [
        r'\badolescent\b', r'\bteen(?:ager)?\b',
        r'\byoung people\b', r'\byoung person\b',
    ]),
    ('Persons living in rural/remote areas', [
        r'\brural\s+(?:area|community|population|household|region|setting|dweller)\b',
        r'\bremote\s+area\b',
    ]),
    ('Persons affected by armed conflict', [
        r'\barmed conflict\b', r'\bwar crime\b', r'\boccupied territory\b',
        r'\bhumanitarian law\b', r'\bIHL\b', r'\bhostilities\b',
        r'\bcombatant\b', r'\bforced displacement\b', r'\bpost.conflict\b',
    ]),
    ('Persons living in poverty', [
        r'\bpovert', r'\bindigent\b', r'\bextreme poverty\b',
        r'\bimpoverish', r'\bdestitut',
        r'\bpoor\s+(?:people|persons|communities|families)\b',
    ]),
    ('Internally displaced persons', [
        r'\bIDPs?\b', r'\binternally displaced\b', r'\binternal displacement\b',
        r'\bforced eviction\b',
    ]),
    ('Persons in street situations', [
        r'\bstreet\s+(?:child|person|people|youth)\b', r'\bhomeless(?:ness)?\b',
    ]),
    ('Children in alternative care', [
        r'\bfoster\s+(?:care|child|parent)\b', r'\borphan',
        r'\bchildren? in (?:alternative|substitute) care\b',
    ]),
    ('Non-citizens and stateless', [
        r'\bstateless(?:ness)?\b', r'\bnon.citizen\b', r'\bnon.nationals?\b',
    ]),
    ('Persons living with HIV/AIDS', [
        r'\bHIV\b', r'\bAIDS\b', r'\bantiretroviral\b',
    ]),
    ('LGBTI+', [
        r'\bLGBT(?:I|Q)?\+?\b', r'\bsexual orientation\b', r'\bgender identity\b',
        r'\bhomosexual(?:ity)?\b', r'\bbisexual\b', r'\btransgender\b',
        r'\bintersex\b', r'\bsame.sex\b',
    ]),
    ('Roma, Gypsies, Sinti and Travellers', [
        r'\bRoma\b', r'\bGyps(?:y|ies)\b', r'\bSinti\b',
    ]),
    ('Persons affected by natural disasters', [
        r'\bnatural disaster\b', r'\bdisaster\s*(?:risk|relief|response|recovery)\b',
        r'\bearthquake\b', r'\bflood(?:ing)?\b', r'\bcyclone\b', r'\bdrought\b',
        r'\bclimate change\b',
    ]),
]
COMPILED_LABELS = [(label, [re.compile(p, re.IGNORECASE) for p in pats])
                   for label, pats in LABEL_PATTERNS]


# ---------------------------------------------------------------------------
# OHCHR download — same flow as ingest_new_gcs.py
# ---------------------------------------------------------------------------
def fetch_url(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read()


def discover_pdf_url(signature: str) -> str | None:
    """Find a working PDF URL for a UN document signature.

    Strategy (first hit wins):
      1. documents.un.org/api/symbol/access?s={SIG}&l=en&t=pdf
         — the modern UN documents portal API; serves the actual PDF
         directly (Content-Type: application/pdf) for A/, A/HRC/, E/CN.4/
         signatures going back to at least 2003. This is the primary route.
      2. daccess-ods.un.org/access.nsf/Get?Open&DS={SIG}&Lang=E
         — the legacy Official Document System (slow / can hang).
      3. OHCHR Download.aspx (treaty-body-only; useful for joint GCs).
      4. None — caller logs and skips.
    """
    # 1. documents.un.org symbol-access API — primary route for SR/SP reports.
    docs_url = (
        'https://documents.un.org/api/symbol/access'
        f'?s={signature}&l=en&t=pdf'
    )
    try:
        req = urllib.request.Request(docs_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            ctype = resp.headers.get('Content-Type', '')
            head = resp.read(8)
            if head.startswith(b'%PDF') or 'application/pdf' in ctype:
                return docs_url
    except Exception:
        pass

    # 2. ODS — legacy fallback route for SR/SP reports.
    ods_url = f'https://daccess-ods.un.org/access.nsf/Get?Open&DS={signature}&Lang=E'

    # 2. OHCHR (treaty body) Download.aspx — used by ingest_new_gcs.py for GCs.
    enc = urllib.parse.quote(signature, safe='')
    ohchr_url = (
        'https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/'
        f'Download.aspx?symbolno={enc}&Lang=en'
    )

    # Try ODS first — quick HEAD-style check by reading the first ~1KB to
    # confirm it's a PDF. We can't HEAD because daccess-ods follows redirects.
    try:
        req = urllib.request.Request(ods_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
            head = resp.read(8)
            if head.startswith(b'%PDF'):
                return ods_url
    except Exception:
        pass

    # Fall back to OHCHR landing page (only useful for treaty body docs).
    try:
        html = fetch_url(ohchr_url).decode('utf-8', errors='replace')
        m = re.search(
            r'title="English[^"]*pdf"[^>]*href="(https://docstore[^"]+)"',
            html,
        )
        if m:
            return m.group(1).replace('&amp;', '&')
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# PDF → paragraphs (same as ingest_new_gcs.py)
# ---------------------------------------------------------------------------
def extract_paragraphs(pdf_path: Path) -> list[dict]:
    doc = fitz.open(pdf_path)
    pages_text = [page.get_text("text") for page in doc]
    full = "\n".join(pages_text)
    doc.close()

    lines = full.split('\n')
    skip_pat = re.compile(
        r'^\s*(GE\.\d+|[A-Z]+/[A-Z]+/[A-Z0-9]+/\d+|page \d+|\d+\s*$)\s*$')
    clean = [ln for ln in lines if not skip_pat.match(ln.strip())]
    text = '\n'.join(clean)

    text = re.sub(r'-\n', '', text)
    text = re.sub(r'(?<=[a-z,])\n(?=[a-z(])', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)

    para_split = re.split(r'(?m)^\s*(\d{1,3})\.\s+', text)
    paragraphs = []
    if len(para_split) >= 3:
        for i in range(1, len(para_split) - 1, 2):
            num = para_split[i]
            body = para_split[i + 1].strip()
            if len(body) < 30:
                continue
            body = re.sub(r'\s+', ' ', body).strip()
            paragraphs.append({'ID': f'{num}.', 'Labels': [], 'Text': body})
    else:
        for i, chunk in enumerate(re.split(r'\n\s*\n', text), 1):
            chunk = chunk.strip()
            if len(chunk) > 50:
                paragraphs.append({
                    'ID': f'{i}.', 'Labels': [],
                    'Text': re.sub(r'\s+', ' ', chunk),
                })
    return paragraphs


def label_paragraph(text: str) -> list[str]:
    found = []
    for label, pats in COMPILED_LABELS:
        if any(p.search(text) for p in pats):
            found.append(label)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Mandate-holder + report-type derivation
# ---------------------------------------------------------------------------
def holder_for_year(holders: list[tuple[int, str]], year: int) -> str:
    for y_max, name in holders:
        if year <= y_max:
            return name
    return holders[-1][1]


def parse_sessions(sig: str) -> tuple[int | None, int | None]:
    m = re.match(r'^A/HRC/(\d+)/', sig)
    if m:
        return int(m.group(1)), None
    m = re.match(r'^A/(\d{2,3})/', sig)
    if m and not sig.startswith('A/HRC/'):
        return None, int(m.group(1))
    return None, None


def safe_filename(s: str) -> str:
    s = re.sub(r'[/\\:.\s]+', '_', s)
    s = re.sub(r'[^A-Za-z0-9_-]', '', s)
    return s


# ---------------------------------------------------------------------------
# Main ingestion driver
# ---------------------------------------------------------------------------
def ingest(mandate_slug: str, *, force: bool = False, limit: int | None = None) -> dict:
    if mandate_slug not in MANDATES:
        raise SystemExit(f'Unknown mandate: {mandate_slug!r}. '
                         f'Available: {sorted(MANDATES)}')
    cfg = MANDATES[mandate_slug]
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    SP_LABELED_DIR.mkdir(parents=True, exist_ok=True)

    sp_meta = json.loads(SP_META.read_text())
    existing_sigs = {r.get('Signature', '').strip() for r in sp_meta}

    today = date.today().isoformat()
    new_records = []
    skipped = []
    failed = []

    reports = cfg['reports'][:limit] if limit else cfg['reports']

    for year, sig, presented, subject in reports:
        if sig in existing_sigs and not force:
            skipped.append((sig, 'already in metadata'))
            continue

        print(f'\n[{sig}] ({year}) {subject[:60]}…')
        holder = holder_for_year(cfg['mandate_holders'], year)
        hrc, ga = parse_sessions(sig)

        # 1. Discover PDF URL
        pdf_url = discover_pdf_url(sig)
        if not pdf_url:
            print('  ✗ could not resolve PDF URL')
            failed.append((sig, 'no PDF URL'))
            continue

        # 2. Download
        pdf_path = PDF_CACHE / f'{safe_filename(sig)}.pdf'
        if not pdf_path.exists() or force:
            try:
                pdf_bytes = fetch_url(pdf_url, timeout=45)
            except Exception as e:
                print(f'  ✗ download failed: {e}')
                failed.append((sig, f'download error: {e}'))
                continue
            if not pdf_bytes.startswith(b'%PDF'):
                print(f'  ✗ not a PDF (got {len(pdf_bytes)}b)')
                failed.append((sig, 'not a PDF'))
                continue
            pdf_path.write_bytes(pdf_bytes)
        time.sleep(0.4)  # courtesy throttle

        # 3. Extract paragraphs
        try:
            paras = extract_paragraphs(pdf_path)
        except Exception as e:
            print(f'  ✗ paragraph extraction failed: {e}')
            failed.append((sig, f'extraction: {e}'))
            continue
        if not paras:
            print('  ✗ no paragraphs extracted')
            failed.append((sig, 'no paragraphs'))
            continue

        # 4. Apply labels
        labeled = []
        n_lbl = 0
        for p in paras:
            labels = label_paragraph(p['Text'])
            if labels:
                n_lbl += 1
            labeled.append({**p, 'Labels': labels})
        print(f'  ✓ {len(paras):3d} paragraphs ({n_lbl} labelled)')

        # 5. Write paragraph file
        out_filename = f"{cfg['committee_label'].replace(' ', '_')}_{safe_filename(sig)}.json"
        (SP_LABELED_DIR / out_filename).write_text(
            json.dumps(labeled, ensure_ascii=False, indent=2))

        # 6. Build metadata record
        rec = {
            'File PATH': f'/home/lszoszk/mysite/json_data_sp/{out_filename}',
            'Name': subject,
            'Simplified Name': subject[:90],
            'Signature': sig,
            'Adoption Date': str(year),
            'Adoption Year': year,
            'Committee': cfg['committee_label'],
            'Mandate holder': holder,
            'Presented': presented,
            'Link': f'https://docs.un.org/en/{sig}',
            'reportType': 'thematic',
            'paragraphCount': len(labeled),
            'wordCount': sum(len(p['Text'].split()) for p in labeled),
            'labelCount': sum(len(p['Labels']) for p in labeled),
            'firstAddedAt': today,
            'lastVerifiedAt': today,
            'languagesAvailable': ['en'],
        }
        if hrc is not None:
            rec['hrcSession'] = hrc
        if ga is not None:
            rec['gaSession'] = ga
        new_records.append(rec)

    # Append metadata
    if new_records:
        sp_meta.extend(new_records)
        SP_META.write_text(json.dumps(sp_meta, ensure_ascii=False, indent=2))

    return {
        'mandate': mandate_slug,
        'requested': len(reports),
        'ingested': len(new_records),
        'skipped': skipped,
        'failed': failed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mandate', help='Mandate slug to ingest (e.g. "disability")')
    ap.add_argument('--list', action='store_true', help='List configured mandates')
    ap.add_argument('--force', action='store_true', help='Re-download and re-ingest even if signature exists')
    ap.add_argument('--limit', type=int, default=None, help='Limit number of reports (for testing)')
    args = ap.parse_args()

    if args.list:
        for slug, cfg in MANDATES.items():
            print(f'  {slug:20s} {cfg["full_name"]} — {len(cfg["reports"])} reports')
        return 0

    if not args.mandate:
        ap.print_help()
        return 1

    result = ingest(args.mandate, force=args.force, limit=args.limit)
    print(f'\n=== {result["mandate"]} ingestion summary ===')
    print(f'  Requested:  {result["requested"]}')
    print(f'  Ingested:   {result["ingested"]}')
    print(f'  Skipped:    {len(result["skipped"])}')
    print(f'  Failed:     {len(result["failed"])}')
    if result['failed']:
        print('\nFailures:')
        for sig, why in result['failed']:
            print(f'  {sig}: {why}')
    return 0 if not result['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())
