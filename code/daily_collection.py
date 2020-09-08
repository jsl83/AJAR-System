# This script is run daily to collect, process, and store papers published the previous day

# Import relevant libraries

import pandas as pd
import requests
import time
import pyodbc
import pickle
import numpy as np
from scipy import sparse
from langdetect import detect
from datetime import date, timedelta
from nltk.stem.wordnet import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer

# Load pickled model (tfdif vectorizer) and features from previous papers

wl = WordNetLemmatizer()
vec = pickle.load(open('../data/vectorizer.csv', 'rb'))
old_features = sparse.load_npz('../data/features.npz')


# Try/except for the language detection - would ocasionally throw error which would halt collection process
def detect_lang(text):
    try:
        return detect(text)
    except:
        return 'error'

# Function to remove non-alpha characters and lemmatize all words for a paper's abstract
def parser(title):
    
    '''Removes any non-alphabetical characters, converts to lower case, and lemmatizes each word in a document'''
    
    letters = re.sub('[^a-zA-Z]', ' ', title)
    letters = letters.lower()
    words = re.split('\s+', letters)
    words = [wl.lemmatize(x) for x in words]
    return (' '.join(words))

# Create empty dictionary framework for storing data
papers = {'title':[], 'abstract':[], 'link':[], 'date':[],
          'type':[], 'authors':[], 'journal':[]}

# String for yesterday's date
today = date.today().strftime('%Y-%m-%d')
yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

# Connect to SQL server for data upload
cnxn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=ga-cc12-s5.database.windows.net;DATABASE=capstone;UID=[REDACTED];PWD=[REDACTED]')
cursor = cnxn.cursor()

start = True
x = 0

# This for loop pings the Spring API for papers from the previous day (50 papers per request limit). Loop continues until less than 50 papers are pulled. Data is stored in the dictionary created above
while start:

    data = requests.get("http://api.springer.com/metadata/json?api_key=4a6226d4feb9e43bf17f2a83b4cce338&q=type:Journal onlinedatefrom:" + yesterday + " onlinedateto:" + today + "&s=" + str(x) + "&p=50")
    ream = data.json()['records']
    papers['title'] += [str(z.get('title')) for z in ream]
    papers['abstract'] += [str(z.get('abstract')) for z in ream]
    papers['link'] += [str(z.get('url')[0].get('value')) for z in ream]
    papers['date'] += [str(z.get('publicationDate')) for z in ream]
    papers['type'] += [str(z.get('contentType')) for z in ream]
    papers['journal'] += [str(z.get('publicationName')) for z in ream]
    print(papers['date'][-1])
    for paper in ream:
        authors = ''
        for author in [y.get('creator') for y in paper.get('creators')]:
            authors += author + ' | '
        authors = authors[:-3]
        papers['authors'].append(authors)

    if len(ream) < 50:
        start = False
    else:
        time.sleep(3)
        x += 50

# Data cleaning
# Remove duplicates, papers from the incorrect date (API returns papers for the first days of each month for the year for some reason despite date search parameters). Remove papers not in English as well as those with empty or symbol-filled abstracts/titles. Removes redacted/corrected papers (low abstract character count). Assign unique id number to each paper

df = pd.DataFrame.from_dict(papers)
df.drop_duplicates(subset='title', inplace=True)
df = df[df['type'] == 'Article']
df = df[df['date'] == yesterday]
df = df[['{' not in df['title'][x] and '???' not in df['abstract'][x] for x in df.index]]
df = df[[detect_lang(df['title'][x]) == 'en' and detect_lang(df['abstract'][x]) == 'en' for x in df.index]]
df = df[[len(df['abstract'][x]) > 150 for x in df.index]]
df.sort_values(by=['date', 'title'], inplace=True)
paper_id = list(cursor.execute("SELECT MAX(id) FROM papers;").fetchall()[0])[0] + 1
df['p_abstract'] = [parser(x) for x in df['abstract']]        
df.sort_values(by='title', inplace=True)
df['id'] = np.arange(paper_id, paper_id + len(df))


# Use pickled vectorizer to create features for new papers and concatenate it with the old feature matrix
new_features = vec.transform(df['p_abstract'])
all_features = sparse.vstack([old_features, new_features])

sparse.save_npz('../data/features.npz', all_features)

# Insert new papers to the SQL table
for index, row in df.iterrows():
    cursor.execute("INSERT INTO papers (title, abstract, link, date, journal, authors, id) values(?,?,?,?,?,?,?)",
                    row['title'], row['abstract'], row['link'], row['date'], row['journal'], row['authors'], row['id'])

cnxn.commit()
cursor.close()