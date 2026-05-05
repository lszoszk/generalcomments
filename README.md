# UN Treaty Bodies Search and Analysis App

<a href="https://zenodo.org/doi/10.5281/zenodo.10495719"><img src="https://zenodo.org/badge/741047917.svg" alt="DOI"></a>

This Flask application, also available at <a href="https://lszoszk.pythonanywhere.com/">lszoszk.pythonanywhere.com</a>, is designed to perform in-depth analysis and search through a collection of the General Comments/Recommendations adopted by the UN Treaty Bodies. It offers functionalities such as keyword searching, concerned groups filtering, analysis of collocations and export search results to Excel.  🇺🇳 🔍📊📄

## Description

The app processes JSON data, enabling users to search through the General Comments/Recommendations (paragraph-level search) based on keywords, concerned groups/persons labels, and Treaty Bodies. It features an advanced text analysis pipeline using NLTK for tokenization, term frequencies, bigram extraction, and custom stopwords processing. The application also provide a search-within-search functionality, which allows for a more advanced filtering of search results.

## Getting Started

### Dependencies

- Python 3.6+
- Flask
- Pandas
- NLTK
- BeautifulSoup
- `GC-info.json` file for the app's document metadata

### Installation

1. Clone the repository:
   ```
   git clone [URL of this repository]
   ```
2. Navigate to the project directory:
   ```
   cd [project_name]
   ```

### Executing Program

1. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```
2. Run the Flask application:
   ```
   python app.py
   ```
3. Access the application through a web browser at `localhost:5000`.

## Features

- **Advanced Search** 🔍: A robust search functionality that allows users to filter relevant paragraphs from the documents based on keyword, concerned groups/persons (e.g., children, women, indigenous peoples), and by the UN Treaty Bodies (e.g., Committee on the Rights of the Child, Committee on Economic, Social and Cultural Rights).
- **Text Analysis** 📊: Text processing capabilities, leveraging the NLTK for word frequencies, bigram analysis, custom UN-related stopwords list, and search within search results functionality.
- **Custom Labels and Stopwords** 🏷️: Ability to define and use custom labels (e.g., concerned groups, human rights issues) and custom stopwords for text analysis.
- **Interactive Results** 💡: Highlights search terms and displays results interactively.
- **Data Export** 📁: Export search results to Excel format for further analysis.

## Screenshots
![search.png](img%2Fsearch.png)
<em>Main page with search functionality.</em>


![search_results.png](img%2Fsearch_results.png)
<em>Search results. You can visit the source document (OHCHR website) and copy it to a clipboard with automatically generated references.</em>


![analytical_dashboard.png](img%2Fanalytical_dashboard.png)
<em>Analytical dashboard. Insert a query in "Narrow your search" to run an additional, dynamic search within your search results.</em>


![dark_mode.png](img%2Fdark_mode.png)
<em>Dark mode of the application.</em>

## Help

If you encounter any issues, please check if all dependencies are correctly installed and the `GC-info.json` file is properly formatted and located in the root directory of the project.

## Author

[Łukasz Szoszkiewicz](https://lszoszk.github.io/)

E-mail: [l.szoszkiewicz@amu.edu.pl](mailto:l.szoszkiewicz@amu.edu.pl)

[Zuzanna Kowalska](https://www.linkedin.com/in/zuzanna-kowalska-a0a027218/)

E-mail: [zuzkow4@st.amu.edu.pl](mailto:zuzkow4@st.amu.edu.pl)

## Version History

* 0.1. Initial Release (8 January 2024)
  - Includes General Comments adopted by the Committee on the Rights of the Child and the Committee on Economic, Social and Cultural Rights.


* 1.0. Full Release (31 January 2025)
  - Incorporates General Comments from all treaty bodies.
  - Enhancements and updates based on feedback from the initial release.

## License

This repository ships **two distinct works under two distinct licences**:

- **Software** (the dashboard, build pipeline, all source code) is
  released under the
  [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.txt) —
  see [`LICENSE`](LICENSE). Anyone running a modified copy as a hosted
  service must release their modifications under the same licence.
- **Curated dataset** (the paragraph-level corpus, document metadata,
  section annotations, footnote cross-reference resolutions, concerned-
  group labels, and any other human-authored data files) is licensed
  under
  [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)](https://creativecommons.org/licenses/by-nc-sa/4.0/) —
  see [`LICENSE-DATA`](LICENSE-DATA). Academic and non-commercial reuse
  is welcome with attribution; commercial use requires permission.

The underlying UN documents (General Comments, jurisprudence, Special
Procedures reports) remain under the
[United Nations content terms](https://www.un.org/en/about-us/copyright);
they are not re-licensed by this project.

See [`NOTICE`](NOTICE) for the full split and citation guidance, and
[`CITATION.cff`](CITATION.cff) for machine-readable citation metadata.

### Citation

```
Szoszkiewicz, Ł. & Kowalska, Z. (2026). UNHRD — UN Human Rights
Database (paragraph-level search interface for UN Treaty Body General
Comments). https://lszoszk.github.io/generalcomments/
```

When citing individual paragraphs in academic work, please reference
the original UN document signature (e.g. `CRC/C/GC/25 ¶12`), not this
database.

## Acknowledgments

* [Flask](https://flask.palletsprojects.com/)
* [Natural Language Toolkit (NLTK)](https://www.nltk.org/)
* [Pandas](https://pandas.pydata.org/)