# Import flask and create the app class for WSGI implementation

from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
if __name__ == '__main__':
    app.run()

# Import other necessary libraries    

from datetime import date, timedelta, datetime
import pyodbc
import numpy as np
from scipy import sparse
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

"""
Session variable reference:
user = unique user id number, used for saving/referencing favorited papers
f_id = list of paper ids in users favorites
s_id = list of paper ids for the current search results list (or journal names for journal searching)
s_no = reference number for index of s_id for the results display list to start with, since the page only shows 10 items at once
r_id = list of paper ids of recommendations/similar articles to the current paper
fr_id = list of paper ids for recommendations to the users favorites
f_ch = Boolean for whether the favorites list has changed - signals app to recalculate daily recommendations
l/r_message = Page specific errors/notification messages
which_list = Tells which context the results screen is showing (favorites/search results/journals)
"""

# Load feature files (preprocessed during data collection)

features = sparse.load_npz('../data/features.npz')

# Function which converts SQL response object into dictionary {Paper id: [Paper title, paper journal]}
def to_dict(sql):
    pl = list(sql)
    paper_dict = {x[-1]:[x[0],x[1]] for x in pl}
    return paper_dict

# Function which determines length of object list and prepares the variables for displaying those results
def init_list(results):
    session['s_no'] = 0
    if len(results) <= 10:
        plen = len(results)
        nex=False
    else:
        plen = 10
        nex = True
    return plen, nex

# Returns papers most similar to the paper with id = pid by cosine similarity. Defaults to returning top five papers above the threshold score of 0.3
def get_matches(pid, num=5, drop=True, group=False):
    if not group:
        pid = int(pid)
        pid -= 1
        pid = features[pid].toarray()
    scores = cosine_similarity(pid, features)[0]
    reverse = scores.copy()
    reverse.sort()
    reverse = reverse[::-1]
    if drop:
        top = reverse[1:num+1]
    else:
        top = reverse[:num+1]
    return [list(scores).index(x) + 1 for x in top if x > 0.3]

# Returns the papers most similar to a group of papers (list of ids) used for daily recommendations. Returns up to top 5 (default) papers with cosine score above 0.2 (lower threshold as quantity of papers is much lower for a daily pull
def comp_match(ids, pids, num=5):
    
    # Get index numbers from SQL and pulls the corresponding feature rows (paper ids and feature matrix indices are synced)
    rec_ids = list(cursor.execute("SELECT MIN(id), MAX(id) FROM papers WHERE date='" + session['date'] + "'").fetchall()[0])
    if rec_ids[0] is None:
        return []
    rec_features = features[np.arange(rec_ids[0]-1,rec_ids[1]),:]
    rows = rec_features.shape[0]
    
    # Placeholders/variables for results
    scores = []
    matches = []
    over_threshold=True
    x = 0
    
    # Calculate cosine similarities for each paper in ids (favorites) against each paper of the most recent day. Sort scores by ascending order in "reverse" list
    for pf in ids:
        scores += list(cosine_similarity([pf], rec_features)[0])
    reverse = scores.copy()
    reverse.sort()
    reverse = reverse[::-1]
    
    # Moves down scores list and fetch corresponding paper id. If paper is not already in favorites or the results list, add to results. Once the number of papers is high enough or cosine scoree drops low enough, breaks loop  
    while len(matches) < num and over_threshold:
        score = reverse[x]
        if score < 0.2:
            over_threshold = False
            break
        index = scores.index(score)+1
        mid = index%rows + rec_ids[0] - 1
        if mid not in pids and mid not in matches:
            matches.append(mid)
        x += 1
    
    # Return nothing if no matches of sufficient quality were found, otherwise return list of recommended paper ids
    if len(matches) == 0:
        return []
    else:
        return matches

# Retrieve paper titles and journals for a range of paper ids in a list (list slice ids[start:stop]). If journals is called, then just returns slice of the original list (only need journal names)
def get_plist(ids, start, stop, journal = False):
    if len(ids) == 0:
        return []
    if journal:
        return ids[start:stop]
    else:
        sql_query = "SELECT title, journal FROM papers WHERE id='"
        for x in ids[start:stop]:
            sql_query += str(x) + "' OR id='"
        sql_query = sql_query[:-8]
        sql_query += " ORDER BY id DESC"

        return [[y[0], y[1]] for y in list(cursor.execute(sql_query).fetchall())]
    
app.secret_key = b'\xcbl\x92r\xdb\xaa\xfb|<\xbf\x156\xaeM\n\xde'

# Establish connection to SQL server
cnxn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=ga-cc12-s5.database.windows.net;DATABASE=capstone;UID=[REDACTED];PWD=[REDACTED]')
cursor = cnxn.cursor()

# Log in page - clears session to erase persistent session variables to allow clean slate for new users logging in
@app.route("/")
def home():
    session.clear()
    return render_template("home.html")

# Log in button function. Directs user to user home page, otherwise bounces back to log in page with error message
@app.route("/login")
def login():
    user_input = request.args
    if user_input['button'] == 'login':
        # Check for errors - user already exists/incorrect passwords etc
        if list(cursor.execute("SELECT COUNT(name) FROM users WHERE name = '" + user_input['name'] + "'").fetchall()[0])[0] == 0:
            return render_template("home.html", error="No user found with that name")
        else:
            info = list(cursor.execute("SELECT * FROM users WHERE name = '" + user_input['name'] + "'").fetchall()[0])
            if user_input['pass'] != info[2]:
                return render_template("home.html", error="Incorrect user name/password combination")
            else:
                session.clear()
                session['user'] = info[0]
                session.modified=True
                return redirect(url_for('user_home'))
    if user_input['button'] == 'register':
        return redirect(url_for('reg_display'))

# Weird redirect function - not the best way but set it up early, don't want to mess with it
@app.route("/register")
def reg_display():
    return render_template('register.html')

# Registration function - adds new user to SQL database and logs in to user home page
@app.route("/create")
def register():
    user_input = request.args
    if user_input['button']=='back':
        session.clear()
        return redirect(url_for('home'))
    else:
        # Check for errors (duplicate user names, mismatched passwords, etc)
        if len(user_input['name']) == 0:
            return render_template('register.html', error='User name cannot be blank')
        elif list(cursor.execute("SELECT COUNT(name) FROM users WHERE name = '" + user_input['name'] + "'").fetchall()[0])[0] > 0:
            return render_template('register.html', error='User name already exists')
        elif user_input['pass'] != user_input['passconf']:
            return render_template('register.html', error='Passwords do not match')
        else:
            # Assign unique user id number, add user to SQL database
            new_id = list(cursor.execute("SELECT MAX(id) FROM users;").fetchall()[0])[0] + 1
            cursor.execute("INSERT INTO users (id, name, pass) values (?,?,?)", new_id, user_input['name'], user_input['pass'])
            cnxn.commit()
            session['user'] = new_id
        return redirect(url_for('user_home'))

# Main user home page function. First thing user sees when logging in
@app.route("/user_home")
def user_home():
    if 'user' not in session:
        return redirect(url_for('home'))
    else:
        r_message = ''
        # Check for the presence of session variables - if not found, indicates this is the very first login, so assigns starting values for various session variables and calculates daily recommendations
        if 'f_id' not in session:
            user_favs = [x[0] for x in cursor.execute("SELECT p_id FROM favs WHERE use_id = '" + str(session['user']) + "'").fetchall()]
            if len(user_favs) == 0:
                session['f_id'] = []
            else:
                session['f_id'] = list(user_favs)
            session['f_ch'] = True
            session['date'] = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
            session['p_num'] = list(cursor.execute("SELECT COUNT(*) FROM papers WHERE date='" + session['date'] + "'").fetchall()[0])[0]
            session['l_message'] = ''
        fl = len(session['f_id'])
        
        # Calculate daily recommendations based on the users favorited articles. Perform clustering if the number of favorites is greater than 5 (to hopefully provide more general recommendations for overall interests)
        if fl == 0:
            r_message = 'No articles saved. Favorite articles to receive daily recommendations'
            session['fr_id'] = []
            start = []
        elif session['f_ch']:
            fids = [features[int(x)-1].toarray()[0] for x in session['f_id']]
            # Adds variable - for low paper counts, we "bolster" the favorites with matching papers to each article and use that for clustering
            if fl > 5:
                if fl < 15:
                    adds = 1
                    if fl < 9:
                        adds = 2
                    for paper in session['f_id']:
                        fids += [features[x-1].toarray()[0] for x in get_matches(paper, num=adds)]
                best = 0
                labels = []
                fids = np.matrix(fids)
                
                # Perform K-Means clustering with k ranging from 2 to 4: Selects the clustering with the highest silhouette score
                for y in range(2,5):
                    km = KMeans(n_clusters=y)
                    km.fit(fids)
                    sil = silhouette_score(fids, km.predict(fids))
                    if sil > best:
                        best = sil
                        labels = km.labels_[:len(session['f_id'])]
                grouped_features = []
                for x in range(max(labels)+1):
                    pgroup = fids[[y for y, z in enumerate(labels) if z == x],:]
                    grouped_features.append(sum(map(np.array, pgroup)))
                fids = grouped_features
            
            # Save recommendations, assign variables for html display
            session['fr_id'] = comp_match(fids, session['f_id'])
            session.modified=True
            start = np.arange(len(session['fr_id']))
            if len(session['fr_id']) == 0:
                r_message = 'Did not find papers of interest from ' + datetime.strptime(session['date'], "%Y-%m-%d").strftime('%B %d, %Y')
            session['f_ch'] = False

        session['which_list'] = ''
        session['r_id'] = {}
        titles = get_plist(session['fr_id'], 0, len(session['fr_id']))
        return render_template('user_home.html', start = np.arange(len(session['fr_id'])), papers=titles, ids=sorted(session['fr_id'],reverse=True), rec_message=r_message, number=session['p_num'], date=datetime.strptime(session['date'], "%Y-%m-%d").strftime('%B %d, %Y'))

# Main search function - breaks up query by spaces and searches for search keywords - all other words are treated as search terms
@app.route("/search")
def search():
    query = request.args['query']
    if len(query) == 0:
        return redirect(url_for('user_home'))
    else:
        words = query.split()
        date, from_date, to_date, journal, terms = '','','','',''
        for word in words:
            word = word.lower()
            # Search for keywords by presence of colon. Parses argument and creates appropriate SQL syntax
            if ':' in word:
                if 'date' in word:
                    date = "p.date='" + word[-10:] + "'"
                elif 'from' in word:
                    from_date = "CONVERT(date, p.date) >= CONVERT(date, '" + word[-10:] + "')"
                elif 'to' in word:
                    to_date = "CONVERT(date, p.date) <= CONVERT(date, '" + word[-10:] + "')"
                elif 'journal' in word:
                    journal = "p.journal='" + word[8:] + "'"
            else:
                terms += "p.abstract LIKE '%" + word + "%' AND "
        if len(terms) > 0:
            terms = terms[:-5]
        
        # Create full SQL query string from parsed segments
        sql_query = 'SELECT id FROM papers p WHERE '
        for x in [date, from_date, to_date, journal, terms]:
            if len(x) > 0:
                sql_query += x + ' AND '
        sql_query = sql_query[:-5]
        sql_query += ' ORDER BY id DESC'
        
        # Save paper ids for the search results and points result page to article search (which_list key)
        session['s_id'] = [x[0] for x in list(cursor.execute(sql_query).fetchall())]
        session['which_list'] = 'paper_list.html'
        if len(session['s_id']) == 0:
            return render_template('paper_list.html', start=[], papers=[], ids=[], prev=False, next_list=False, l_message="No articles matched your search criteria")
        
        # Initialize variables for html display
        plen, nex = init_list(session['s_id'])
        if nex:
            nex_num = 10
        else:
            nex_num = 0
        session['l_message'] = "Displaying " + str(len(session['s_id'])) + " articles for your search: " + query
        session.modified = True
        titles = get_plist(session['s_id'], 0, plen)
        return render_template('paper_list.html', start=np.arange(0, plen), papers=titles, ids=session['s_id'], prev=False, next_list=nex, l_message=session['l_message'], nextno=nex_num)

# Function for displaying information on individual papers as well as list of similar articles
@app.route("/s_display")
def s_display():
    paper_id = int(request.args['button'])
    
    # Pull information from SQL database
    info = list(cursor.execute("SELECT * FROM papers WHERE id = '" + str(paper_id) + "'").fetchall()[0])
    r_ids, r_titles = [],[]
    
    # Set favorite/unfavorite button context depending on if it's favorited already or not
    if paper_id in session['f_id']:
        fav = "Unfavorite"
    else:
        fav = "Favorite"
        
    # Find similar papers and assign appropriate variables for HTML display
    match_ids = get_matches(paper_id)
    if len(match_ids)!=0:
        message=''
        sql_query = "SELECT title, journal, id FROM papers WHERE id='"
        for x in match_ids:
            sql_query += str(x) + "' OR id='"
        sql_query = sql_query[:-8]
        session['r_id']=to_dict(cursor.execute(sql_query).fetchall())
        session.modified=True
        r_ids = sorted(list(session['r_id'].keys()))
        r_ids = r_ids[::-1]
        r_titles = [session['r_id'][x] for x in r_ids]
    else:
        message='No sufficiently similar articles found'
        session['r_id'] = {}
    
    return render_template('paper.html', title=info[0], abstract=info[1], authors=info[2], journal=info[3], link=info[4], date="Published on " + datetime.strptime(info[5], "%Y-%m-%d").strftime('%B %d, %Y'), favor=fav, pid=paper_id,
                           start=np.arange(len(session['r_id'])), papers=r_titles, ids=r_ids, no_sim=message)

# Main results navigation function (previous, next buttons). The session[which_list] variable is for this function, as it tells this function which results screen to display
@app.route("/search_move")
def next_search():
    user_input = request.args
    prev, nex = True, True
    prev_num, nex_num = 0, 0
    
    # Reassign pointer to new index in the list, then calculates where the new points where the previous/next buttons refer to and whether they should be displayed or not (front/end of list)
    session['s_no'] = int(user_input['button'])
    if session['s_no'] < 10:
        prev = False
    else:
        prev_num = session['s_no']-10
    start = session['s_no']
    remain = len(session['s_id']) - start
    if remain <= 10:
        plen = remain
        nex=False
    else:
        remain = 10
        nex_num = session['s_no'] + 10
    journal = False
    
    # Conditional for journal list, which differs from the normal paper results
    if session['which_list'] == 'journals.html':
        journal = True
    info = get_plist(session['s_id'], start, start+remain, journal)
    titles = ([0]*start) + info
    return render_template(session['which_list'], start=np.arange(start, start + remain), papers=titles, ids=session['s_id'], prev=prev, next_list=nex, l_message=session['l_message'], prevno=prev_num, nextno=nex_num)

# Redirect function for the top bar navigation buttons that move the user from section to section
@app.route("/nav_menu")
def nav_menu():
    return redirect(url_for(request.args['button']))

# Function for adding/removing a paper to a user's favorites list
@app.route("/fave")
def fave():
    pid = str(int(request.args['button']))
    info = list(cursor.execute("SELECT * FROM papers WHERE id = '" + pid + "'").fetchall()[0])
    
    # Remove from favorites and deletes from SQL table if favorited
    if int(pid) in session['f_id']:
        cursor.execute("DELETE FROM favs WHERE p_id = '" + pid + "' AND use_id='" + str(session['user']) + "'")
        session['f_id'].remove(int(pid))
        fav="Favorite"
    # Performs opposite if not in favorites
    else:
        cursor.execute("INSERT INTO favs (use_id, p_id, title, journal) values (?,?,?,?)", session['user'], pid, info[0], info[3])
        session['f_id'].append(int(pid))
        fav="Unfavorite"
        
    session['f_ch'] = True
    session.modified=True
    cnxn.commit()

    # Carry over recommendations from original display and pushes out the HTML
    if len(session['r_id'])==0:
        message='No sufficiently similar articles found'
        r_titles, r_ids = [], []
    else:
        r_ids = sorted([int(x) for x in list(session['r_id'].keys())])
        r_ids = r_ids[::-1]
        r_ids = [str(x) for x in r_ids]
        r_titles = [session['r_id'][x] for x in r_ids]
        message=''
    return render_template('paper.html', title=info[0], abstract=info[1], authors=info[2], journal=info[3], link=info[4], date=info[5], favor=fav, pid=int(pid),
                           start=np.arange(len(session['r_id'])), papers=r_titles, ids=r_ids, no_sim=message)

# Display list of all saved papers. Similar to search results display in terms of function
@app.route("/favorites")
def favorites(s_number=0):
    plen, nex = init_list(session['f_id'])
    if nex:
        nextnum=10
    else:
        nextnum=0
    session['s_id'] = session['f_id']
    session['s_no'] = s_number
    session['which_list'] = 'favorites.html'
    session['f_ch'] = True
    if len(session['f_id']) == 0:
        dele = False
        message = "No saved articles. Favorite articles to receive daily recommendations"
    else:
        dele = True
        message = "Your saved articles"
    session['s_id'] = sorted(session['s_id'], reverse=True)
    titles = get_plist(session['s_id'], 0, plen)
    return render_template('favorites.html', start=np.arange(0, plen), papers=titles, ids=session['s_id'], prev=False, next_list=nex, l_message=message, nextno=nextnum)

# Display the about page - no functionality, static text
@app.route("/about")
def about():
    return render_template('about.html')

# Display initial journal page - only includes journal search bar, all other values default to null
@app.route("/journals")
def journals():
    session['l_message'] = ''
    return render_template('journals.html',start=[], prev=[], next_list=[], papers=[], ids=[], l_message='')

# Displays list of journals as a result of a journal search
@app.route("/search_journals")
def search_journals():
    search_string = request.args['search_journals']
    query = search_string.split()
    if len(query) == 0:
        return render_template('journals.html')
    
    # Retrieve unique list of journals matching search terms from SQL table
    sql_req = 'SELECT DISTINCT journal FROM papers WHERE '
    for word in query:
        sql_req += "journal LIKE '%" + word + "%' AND "
    sql_req = sql_req[:-5]
    session['s_id'] = [x[0] for x in list(cursor.execute(sql_req).fetchall())]
    
    # Assign variables for HTML display, pointers for search navigation
    plen, nex = init_list(session['s_id'])
    if nex:
        nextnum=10
    else:
        nextnum = 0
    session['which_list'] = 'journals.html'
    if len(session['s_id']) == 0:
        session['l_message'] = "No journals matched your search criteria"
    else:
        session['l_message'] = "Displaying " + str(len(session['s_id'])) + " journals for your search: " + search_string
    return render_template('journals.html', start=np.arange(0,plen), papers=session['s_id'], ids=session['s_id'], prev=False, next_list=nex, l_message=session['l_message'], nextno=nextnum)

# Function for displaying list of papers from a particular journal, similar to using the search parameter "journal:"
@app.route("/j_display")
def j_display():
    journal = request.args['button']
    
    # Pull papers with matching journal from SQL table
    session['s_id'] = [x[0] for x in list(cursor.execute("SELECT id FROM papers WHERE journal = '" + journal + "' ORDER BY id DESC").fetchall())]
    
    # Assign variables for HTML display, points for search navigation
    session['which_list']='paper_list.html'
    plen, nex = init_list(session['s_id'])
    if nex:
        nextnum=10
    else:
        nextnum=0
    session['l_message'] = "Displaying " + str(len(session['s_id'])) + " articles published in " + journal
    titles = get_plist(session['s_id'], 0, plen)
    return render_template('paper_list.html', start=np.arange(0,plen), papers=titles, ids=session['s_id'], prev=False, next_list=nex, l_message=session['l_message'], nextno=nextnum)

