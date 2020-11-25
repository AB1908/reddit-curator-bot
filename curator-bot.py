# Bot listens for mentions or commands. Generates links and sends them back to user as a PM
# Bot also has command to list previously aggregated answers
# Make bot export and backup curated lists regularly. Daily would be nice.
# Maybe: Allow changing when bot creates a reminder message
# Potential abuse by adding same author with multiple comments to a feed
# TODO: Logging system
# TODO: Error handling and recovery. Should fail gracefully
# TODO: non critical path handling
# TODO: Assumption checking, i.e., testing
# TODO: Segregate constants and SQL to separate modules/files
# TODO: Add docstrings

import sqlite3
import praw
import more_itertools

ENTRY_ACCEPTED_TITLE_TEMPLATE = "Adding to list for {}"
ENTRY_ACCEPTED_BODY_TEMPLATE = '[{}\'s answer to the question "{}"]({}) has been stored for the feed dated {}.'
TIME_OF_DAY = "0900"
newline = """
"""
codeline = """
    """
db_conn = sqlite3.connect("feed.db")
db_cursor = db_conn.cursor()
FETCH_FEED = "SELECT submission_text, submission_url, commenter_name FROM history where feed_author = :feed_author and feed_date = :feed_date"
ADD_COMMENT = "INSERT INTO history (submission_id, submission_url, submission_text, submitter_name, comment_id, commenter_name, comment_url, feed_author, feed_date, date_of_addition) VALUES (:submission_id, :submission_url, :submission_text, :submitter_name, :comment_id, :commenter_name, :comment_url, :feed_author, :feed_date, DATETIME('now'));"
TABLE_CREATE = """
CREATE TABLE IF NOT EXISTS history (
submission_id       TEXT    NOT NULL,
submission_url      TEXT    NOT NULL,
submission_text     TEXT    NOT NULL,
submitter_name      TEXT    NOT NULL,
comment_id          TEXT    NOT NULL,
commenter_name      TEXT    NOT NULL,
comment_url         TEXT    NOT NULL,
feed_author         TEXT    NOT NULL,
feed_date           TEXT    NOT NULL,
date_of_addition    TEXT    NOT NULL
);"""
BOT_CREATOR_TEMPLATE = """
-----

I am a bot created by u/AB1908. [Message him](https://reddit.com/message/compose/?to=AB1908) if you have any concerns or want help or just to say thanks! For help, mention the bot and type "HELP!" like this:

    u/-CuratorBot- HELP!"""
BOT_HELP_SUBJECT = "-CuratorBot- help notes"
BOT_HELP_TEXT = """
-----

To add an entry to your weekly feed, mention the bot along the desired feed date like so:

    u/-CuratorBot- dd/mm/yy

To retrieve your feed for the desired date, message or reply to the bot with the following in the body:

    Feed: dd/mm/yy"""

with open("envvars") as envvars:
    CLIENT_ID, CLIENT_SECRET, USERNAME, PASSWORD = envvars.read().splitlines()

def main():
    reddit = praw.Reddit(
        user_agent="-CuratorBot- (by u/AB1908)",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        username=USERNAME,
        password=PASSWORD,
    )

    # TODO: Add mod based uhh...sub handling? Something like that
    subreddit = reddit.subreddit("AskHistorians")
    unread_messages = []
    init_db()
    for message in reddit.inbox.stream():
        unread_messages.append(message)
        if is_mention(message):
            feed_date = message.body.split()[1]
            write_entry_to_db(message, feed_date)
            send_entry_accepted_message(message, feed_date)
        elif requesting_current_feed(message):
            feed_date = message.body.split()[1]
            feed = fetch_feed_from_db(message.author.name, feed_date)
            if feed:
                send_requested_feed(message.author, feed_date, feed, reddit)
            else:
                send_feed_not_found(message.author, feed_date)
        elif help_requested(message):
            send_help_message(message.author)
        reddit.inbox.mark_read(unread_messages)
    db_cursor.close()
    db_conn.close()

def init_db():
    db_cursor.execute(TABLE_CREATE)

def fetch_feed_from_db(username, feed_date):
    db_cursor.execute(FETCH_FEED, {"feed_author": username, "feed_date": feed_date})
    return db_cursor.fetchall()

def write_entry_to_db(mention, feed_date):
    query_params = {"feed_author": mention.author.name, "submission_id": mention.submission.id, "submission_url": mention.submission.url, "submission_text": mention.submission.title, "submitter_name": mention.submission.author.name, "comment_id": mention.parent_id[3:], "commenter_name": mention.parent().author.name, "comment_url": mention.parent().permalink, "feed_date": feed_date}
    try:
        with db_conn:
            db_conn.execute(ADD_COMMENT, query_params)
    except sqlite3.IntegrityError:
        # TODO: Logging and retrying and reraising exception
        print("Could not commit the entry")

def dictify_feed(feed_data):
    # {(submission, submission_url): [author]}
    feed_dict = {}
    for entry in feed_data:
        submission_text = entry[0]
        submission_url = entry[1]
        author = entry[2]
        question = (submission_text, submission_url)
        if question not in feed_dict:
            feed_dict[question] = [author]
        else:
            feed_dict[question].append(author)
    return feed_dict

def stringify_feed(date, feed_data, reddit):
    # Oxford comma used
    # feed_string = "Your feed for {}:\n".format(date)
    # {(submission, submission_url): [author]}
    feed_string = ""
    code_string = ""
    feed_dict = dictify_feed(feed_data)
    for question in feed_dict:
        primary_authors = True
        question_answered = " answered [{}]({}).".format(question[0], question[1])
        for authors in more_itertools.grouper(feed_dict[question], 3):
            authors = ["/u/"+author for author in authors if author is not None]
            if primary_authors:
                author_template = generate_author_template(len(authors))
                feed_string += newline + "- " + author_template.format(*authors) + question_answered
                code_string += codeline + "- " + author_template.format(*authors) + question_answered
                primary_authors = False
            else:
                feed_string += newline + " - " + author_template.format(*authors) + " also answered it too!"
                code_string += codeline + " - " + author_template.format(*authors) + " also answered it too!"
    return feed_string + newline*2 + "&nbsp;" + newline + code_string

def generate_author_template(author_count):
    if author_count == 1:
        author_template = "{}"
    elif author_count == 2:
        author_template = "{} and {}"
    elif author_count == 3:
        author_template = "{}, {}, and {}"
    return author_template

def requesting_current_feed(message):
    return message.body.startswith("Feed: ")

def send_requested_feed(author, date, feed, reddit):
    reply_body = "Your feed for {}:\n{}".format(date, stringify_feed(date, feed, reddit))
    reply_subject = "Feed request for {}".format(date)
    reply_body += BOT_CREATOR_TEMPLATE
    author.message(reply_subject, reply_body)

def send_feed_not_found(author, date):
    reply_body = "No feed found for {}.".format(date)
    reply_subject = "No feed found. Please recheck the date."
    reply_body += BOT_CREATOR_TEMPLATE
    author.message(reply_subject, reply_body)

def send_entry_accepted_message(comment, feed_date):
    # assumes message passed previously is a comment. TEST THIS!
    reply_subject = ENTRY_ACCEPTED_TITLE_TEMPLATE.format(feed_date)
    reply_body = ENTRY_ACCEPTED_BODY_TEMPLATE.format(comment.parent().author, comment.submission.title, comment.context, feed_date)
    reply_body += BOT_CREATOR_TEMPLATE
    comment.author.message(reply_subject, reply_body)

def send_help_message(author):
    author.message(BOT_HELP_SUBJECT, BOT_HELP_TEXT)

def help_requested(message):
    # TODO: case handling and message validation?
    # TODO: modularising bot commands??
    return message.body == "/u/-CuratorBot- HELP!" or message.body == "u/-CuratorBot- HELP!"

def is_mention(message):
    # Does not check if message is actually a comment
    return "u/-CuratorBot-" in message.body.split() or "/u/-CuratorBot-" in message.body.split()

if __name__ == "__main__":
    main()