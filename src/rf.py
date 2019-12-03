#!/usr/bin/env python3

import bitstring
import os
import csv
import dbHelper
import math
import re
import sys
from types import SimpleNamespace
import bisect
from sklearn.ensemble import RandomForestClassifier
import numpy as np

import matplotlib.pyplot as plt
import time
import zipfile

import datasetHelper


def ensureMovieTagsFile(dbConnection, fileName: str, allTagIds, relevanceThreshold: float):
	global DATA_FOLDER
	if os.path.isfile(os.path.join(DATA_FOLDER, fileName)):
		return

	cur = dbConnection.cursor()

	tagBitsCount = math.ceil(len(allTagIds) / 32.0)

	tagIdDict = {val: idx for idx, val in enumerate(allTagIds)}

	movies = {}
	with open(DATA_FOLDER + "/movies.csv", encoding='utf-8') as moviesFile:
		reader = csv.reader(moviesFile)
		next(reader)  # skip the column headers
		for row in reader:
			id = row[0]

			tagIds = list(row[0] for row in cur.execute('select tagId from GenomeScore where movieId=? and relevance>=?', (id, relevanceThreshold)))

			item = SimpleNamespace()
			item.tags = [None] * tagBitsCount

			for t in tagIds:
				# look up the index of the tagId
				index = tagIdDict[t]
				binIndex = math.floor(index / 32.0)

				if item.tags[binIndex] is None:
					item.tags[binIndex] = bitstring.BitArray(length=32)

				item.tags[binIndex].set(1, index % 32)

			movies[id] = item

	with open(os.path.join(DATA_FOLDER, fileName), encoding='utf-8', mode='w', newline='') as f:
		writer = csv.writer(f)
		writer.writerow(['id'] + ['tagBits' + str(i) for i in range(tagBitsCount)])
		for id in movies:
			item = movies[id]
			csvRow = [id]
			for i in range(tagBitsCount):
				if item.tags[i] is None:
					csvRow.append(0)
				else:
					csvRow.append(item.tags[i].int)

			writer.writerow(csvRow)


def ensureMovieTagsTable(fileName, dbConnection):
	cur = dbConnection.cursor()
	TABLE_NAME = 'MovieTags'
	if dbHelper.doesTableExist(TABLE_NAME, cur):
		return

	# Syntax 'create table if not exists' exists, but we don't know if we need to insert rows.
	with open(os.path.join(DATA_FOLDER, fileName), encoding='utf-8') as movieYearGenresFile:
		csvReader = csv.reader(movieYearGenresFile)
		# skip header
		headers = next(csvReader)

		cur.execute("CREATE TABLE {0} (id INTEGER NOT NULL PRIMARY KEY, {1})".format(TABLE_NAME, ','.join([h + ' integer not null' for h in headers[1:]])))
		# table names can't be the target of parameter substitution
		# https://stackoverflow.com/a/3247553/746461

		to_db = list(csvReader)

		cur.executemany("INSERT INTO {0} VALUES (?,{1})".format(TABLE_NAME, ','.join(['?'] * (len(headers) - 1))), to_db)
		dbConnection.commit()

	cur.execute('select * from {0} where id=2'.format(TABLE_NAME))
	print(cur.fetchone())


def ensureMovieYearGenresFile(dataFolder, movieYearGenresFileName):
	if os.path.isfile(os.path.join(dataFolder, movieYearGenresFileName)):
		return

	movies = {}
	global ALL_GENRES
	with open(dataFolder + "/movies.csv", encoding='utf-8') as moviesFile:  # will automatically close the file when exit the with block
		reader = csv.reader(moviesFile)
		next(reader)  # skip the column headers
		for row in reader:
			id = row[0]
			title = row[1].strip()

			m = re.search('\((\d+)\)$', title)
			if m is None:
				print("Movie title doesn't have year. Id=" + id + ", title=" + title, file=sys.stderr)
				continue

			if row[2] == '(no genres listed)':
				continue

			year = int(m.group(1))
			genres = row[2].split('|')

			if (any([bisect.bisect_left(ALL_GENRES, g) < 0 for g in genres])):
				raise Exception('One of {0} is not listed in allGenres.'.format(genres))

			# print('year is %d' % year)
			# print(genres)

			item = SimpleNamespace()
			item.year = year
			item.genres = genres
			movies[id] = item

	genresDict = {val: idx for idx, val in enumerate(ALL_GENRES)}

	with open(dataFolder + "/" + movieYearGenresFileName, encoding='utf-8', mode='w', newline='') as f:
		writer = csv.writer(f)
		writer.writerow(['id', 'year', 'genreBits'])
		for id in movies:
			item = movies[id]
			map = bitstring.BitArray(length=len(ALL_GENRES))
			for i in range(len(item.genres)):
				map[genresDict[item.genres[i]]] = 1

			writer.writerow([id, item.year, map.int])


def ensureMovieYearGenresTable(movieYearGenresFileName, dbConnection):
	cur = dbConnection.cursor()
	TABLE_NAME = 'MovieYearGenres'
	if dbHelper.doesTableExist(TABLE_NAME, cur):
		return

	# Syntax 'create table if not exists' exists, but we don't know if we need to insert rows.
	with open(os.path.join(DATA_FOLDER, movieYearGenresFileName), encoding='utf-8') as movieYearGenresFile:
		csvReader = csv.reader(movieYearGenresFile)
		# skip header
		next(csvReader)

		cur.execute("CREATE TABLE {0} (id INTEGER NOT NULL PRIMARY KEY, year INTEGER NOT NULL, genreBits INTEGER NOT NULL)".format(TABLE_NAME))
		# table names can't be the target of parameter substitution
		# https://stackoverflow.com/a/3247553/746461

		to_db = list(csvReader)

		cur.executemany("INSERT INTO {0} VALUES (?,?,?)".format(TABLE_NAME), to_db)
		dbConnection.commit()

	cur.execute('select * from {0} where id=131162'.format(TABLE_NAME))
	print(cur.fetchone())


def ensureGenomeScoresTable(fileName, dbConnection):
	cur = dbConnection.cursor()
	TABLE_NAME = 'GenomeScore'
	if dbHelper.doesTableExist(TABLE_NAME, cur):
		return

	cur.execute("CREATE TABLE {0} (movieId INTEGER NOT NULL, tagId INTEGER NOT NULL, relevance REAL NOT NULL, PRIMARY KEY(movieId, tagId))".format(TABLE_NAME))
	with open(os.path.join(DATA_FOLDER, fileName), encoding='utf-8') as f:
		csvReader = csv.reader(f)
		next(csvReader)

		to_db = [row for row in csvReader]

		cur.executemany("INSERT INTO {0} VALUES (?,?,?);".format(TABLE_NAME), to_db)
		dbConnection.commit()

	cur.execute('CREATE INDEX tagId ON {0} (tagId ASC)'.format(TABLE_NAME))

	cur.execute('select * from {0} where movieId=1 and tagId=1'.format(TABLE_NAME))
	print('GenomeScore table is created.')
	print(cur.fetchone())


def ensureRatingsTable(fileName, dbConnection):
	cur = dbConnection.cursor()
	TABLE_NAME = 'Ratings'
	if dbHelper.doesTableExist(TABLE_NAME, cur):
		return

	cur.execute("CREATE TABLE {0} (userId INTEGER NOT NULL,movieId INTEGER NOT NULL,rating INTEGER NOT NULL, PRIMARY KEY(userId,movieId))".format(TABLE_NAME))
	with open(os.path.join(DATA_FOLDER, fileName), encoding='utf-8') as f:
		csvReader = csv.reader(f)
		next(csvReader)

		to_db = [row for row in csvReader]

		cur.executemany("INSERT INTO {0} VALUES (?,?,?);".format(TABLE_NAME), to_db)
		dbConnection.commit()

	cur.execute('select * from {0} where userId=1 and movieId=151'.format(TABLE_NAME))
	print(cur.fetchone())


def ensureValidationRatingsTable(fileName, dbConnection):
	cur = dbConnection.cursor()
	TABLE_NAME = 'ValidationRatings'
	if dbHelper.doesTableExist(TABLE_NAME, cur):
		return

	cur.execute("CREATE TABLE {0} (userId INTEGER NOT NULL,movieId INTEGER NOT NULL,rating INTEGER NOT NULL, predict INTEGER, PRIMARY KEY(userId,movieId))".format(TABLE_NAME))
	with open(os.path.join(DATA_FOLDER, fileName), encoding='utf-8') as f:
		csvReader = csv.reader(f)
		next(csvReader)

		to_db = [row for row in csvReader]

		cur.executemany("INSERT INTO {0} VALUES (?,?,?,null);".format(TABLE_NAME), to_db)
		dbConnection.commit()

	cur.execute('select * from {0} where userId=1 and movieId=1653'.format(TABLE_NAME))
	print(cur.fetchone())


def ensureTestRatingTable(fileName, dbConnection):
	cur = dbConnection.cursor()
	TABLE_NAME = 'TestRatings'
	if dbHelper.doesTableExist(TABLE_NAME, cur):
		return

	cur.execute("CREATE TABLE {0} (userId INTEGER NOT NULL,movieId INTEGER NOT NULL, predict integer, PRIMARY KEY(userId,movieId))".format(TABLE_NAME))
	with open(os.path.join(DATA_FOLDER, fileName), encoding='utf-8') as f:
		csvReader = csv.reader(f)
		next(csvReader)

		to_db = [row for row in csvReader]

		cur.executemany("INSERT INTO {0} VALUES (?,?, null);".format(TABLE_NAME), to_db)
		dbConnection.commit()


def flatNestList(a):
	return [item for sublist in a for item in sublist]


def trainClassifier(cursor, clf):
	global ALL_TAG_IDS
	tagBitsCount = math.ceil(len(ALL_TAG_IDS) / 32.0)

	cursor.execute('''
SELECT Ratings.rating, Ratings.userId, MovieYearGenres.year, genreBits, {0} FROM Ratings
join MovieYearGenres on Ratings.movieId=MovieYearGenres.id
join MovieTags on Ratings.movieId=MovieTags.id'''.format(','.join(['tagBits' + str(i) for i in range(tagBitsCount)])))

	trainingData = [list(row[0:3]) +
					list(bitstring.Bits(int=row[3], length=len(ALL_GENRES))) +
					flatNestList([list(bitstring.Bits(int=b, length=32)) for b in row[4:]])
					for row in cursor.fetchall()]

	trainingData = np.array(trainingData, dtype='int32')
	'''    
	if len(trainingData) == 0:
		raise Exception('User {0} does not appear in training set.'.format(userId))
	'''
	y = trainingData[:, 0]
	X = trainingData[:, 1:]
	return clf.fit(X, y)


def predictTest(cursor, clf):
	global ALL_TAG_IDS
	tagBitsCount = math.ceil(len(ALL_TAG_IDS) / 32.0)

	cursor.execute('''
SELECT TestRatings.movieId, TestRatings.userId, MovieYearGenres.year, genreBits, {0} FROM TestRatings
join MovieYearGenres on TestRatings.movieId=MovieYearGenres.id
join MovieTags on TestRatings.movieId=MovieTags.id 
'''.format(','.join(['tagBits' + str(i) for i in range(tagBitsCount)])))

	testingData = [list(row[0:3]) +
				   list(bitstring.Bits(int=row[3], length=len(ALL_GENRES))) +
				   flatNestList([list(bitstring.Bits(int=b, length=32)) for b in row[4:]])
				   for row in cursor.fetchall()]

	testingData = np.array(testingData, dtype='int32')
	predictY = clf.predict(testingData[:, 1:])

	toDB = predictY[:, None]

	# toDB = np.insert(toDB, 1, userId, axis=1)
	toDB = np.insert(toDB, 1, testingData[:, 0], axis=1)
	toDB = np.insert(toDB, 2, testingData[:, 1], axis=1)
	cursor.executemany('update TestRatings set predict=? where movieId=? and userId=?', toDB.tolist())


def classifyUser(con):
	global ALL_TAG_IDS
	tagBitsCount = math.ceil(len(ALL_TAG_IDS) / 32.0)

	cur = con.cursor()
	print('1')
	clf = RandomForestClassifier(n_estimators=100)
	clf = trainClassifier(cur, clf)

	print('2')

	cur.execute('''
SELECT ValidationRatings.movieId, ValidationRatings.userId, MovieYearGenres.year, genreBits, {0} FROM ValidationRatings
join MovieYearGenres on ValidationRatings.movieId=MovieYearGenres.id
join MovieTags on ValidationRatings.movieId=MovieTags.id'''.format(','.join(['tagBits' + str(i) for i in range(tagBitsCount)])))
	validationData = [list(row[0:3]) +
					  #                      list(row[3:4])+
					  list(bitstring.Bits(int=row[2], length=len(ALL_GENRES))) +
					  flatNestList([list(bitstring.Bits(int=b, length=32)) for b in row[4:]])
					  for row in cur.fetchall()]

	validationData = np.array(validationData, dtype='int32')

	print('2')

	# print(validationData[0:5,:])#delete,???
	# print([list(row[0:2]) for row in cur.fetchall()])#delete
	# print([list(bitstring.Bits(int=row[2], length=len(ALL_GENRES))) for row in cur.fetchall()])#delete

	predictY = clf.predict(validationData[:, 1:])
	toDB = predictY[:, None]
	# toDB = np.insert(toDB, 1, userId, axis=1)
	# print(toDB.tolist())
	toDB = np.insert(toDB, 1, validationData[:, 0], axis=1)
	toDB = np.insert(toDB, 2, validationData[:, 1], axis=1)

	print('3')

	# print(toDB.tolist())
	cur.executemany('update ValidationRatings set predict=? where movieId=? and userId=?', toDB.tolist())
	if cur.rowcount == 0:
		raise Exception("No rows are updated.")
	# tree.plot_tree(clf)
	# plt.show()
	con.commit()
	predictTest(cur, clf)
	print('4')
	con.commit()


# cur.execute('select count(*) from ValidationRatings where userId=? and rating=predict', (userId,))
# correct = cur.fetchone()[0]
# # break
# print('user {0}, accuracy is {1:.2f}.'.format(userId, correct / len(predictY)))  # prefer format than %.
# print('User {0} is done.'.format(userId))


def dealWithMissingPrediction(cursor, table: str):
	global FIRST_USERS
	if FIRST_USERS is None:
		cursor.execute('update {0} set predict=? where predict is null'.format(table), (1,))
	else:
		cursor.execute('update {0} set predict=? where predict is null and userId<=?'.format(table), (1, FIRST_USERS))
	print('Fixed {0} empty prediction in table {1}.'.format(cursor.rowcount, table))


def exportTestRatings(cursor, fileName: str):
	cursor.execute('select rowid-1, predict from TestRatings order by rowid')
	data = cursor.fetchall()
	with open(os.path.join(DATA_FOLDER, fileName), 'w', newline="") as f:
		writer = csv.writer(f, delimiter=',')
		writer.writerow(['Id', 'rating'])

		writer.writerows(data)


def main():
	global MAX_ROWS, ALL_GENRES, DATA_FOLDER, ALL_TAG_IDS, FIRST_USERS
	try:
		i = sys.argv.index('--max-rows')
		MAX_ROWS = int(sys.argv[i + 1])
	except:
		MAX_ROWS = None

	DATA_FOLDER = datasetHelper.getDataset()

	movieYearGenresFileName = 'movies-year-genres.csv'
	ensureMovieYearGenresFile(DATA_FOLDER, movieYearGenresFileName)

	con = dbHelper.getConnection(os.path.join(DATA_FOLDER, "sqlite.db"))
	ensureGenomeScoresTable('genome-scores.csv', con)
	ensureMovieYearGenresTable(movieYearGenresFileName, con)

	cur = con.cursor()
	ALL_TAG_IDS = [row[0] for row in cur.execute('select DISTINCT tagId from GenomeScore order by tagId')]

	try:
		i = sys.argv.index('--relevance')
		relevance = float(sys.argv[i + 1])
	except:
		relevance = 0.5

	movieTagsFileName = '{0:.2f}-'.format(relevance) + 'movie-tags.csv'
	ensureMovieTagsFile(con, movieTagsFileName, ALL_TAG_IDS, relevance)
	ensureMovieTagsTable(movieTagsFileName, con)

	ensureRatingsTable('train_ratings_binary.csv', con)
	ensureValidationRatingsTable('val_ratings_binary.csv', con)
	ensureTestRatingTable('test_ratings.csv', con)

	cur.execute('update ValidationRatings set predict=null')
	cur.execute('update TestRatings set predict=null')
	con.commit()

	cur.execute('''
SELECT userid FROM ValidationRatings
UNION
SELECT userId FROM TestRatings''')
	userIds = [row[0] for row in cur.fetchall()]

	try:
		i = sys.argv.index('--first-users')
		FIRST_USERS = int(sys.argv[i + 1])
		userIds = list(filter(lambda x: x <= FIRST_USERS, userIds))
	except:
		pass

	startTime = time.time()

	classifyUser(con)

	dealWithMissingPrediction(cur, 'ValidationRatings')
	dealWithMissingPrediction(cur, 'TestRatings')

	print('Used time: {0}'.format(time.time() - startTime))

	bestAccuracy = 1
	try:
		with open(os.path.join(DATA_FOLDER, 'best accuracy.txt'), mode='r') as f:
			bestAccuracy = float(f.read())
	except:
		pass

	if FIRST_USERS is None:
		cur.execute('''select t.correct, t.total, CAST(t.correct AS float)/t.total as accuracy
from (Select 
(select count(*) from ValidationRatings where rating=predict) as correct,
(select count(*) from ValidationRatings) as total) as t''')
	else:
		cur.execute('''select t.correct, t.total, CAST(t.correct AS float)/t.total as accuracy
from (Select 
(select count(*) from ValidationRatings where rating=predict and userId<={0}) as correct,
(select count(*) from ValidationRatings where userId<={0}) as total) as t'''.format(FIRST_USERS))

	row = cur.fetchone()
	print(row)
	accuracy = row[2]

	if FIRST_USERS is None:
		exportTestRatings(cur, 'submit.csv')
	con.close()

	print('Best accuracy is {0}. This accuracy is {1}.'.format(bestAccuracy, accuracy))
	if FIRST_USERS is None and accuracy > bestAccuracy:
		with open(os.path.join(DATA_FOLDER, 'best accuracy.txt'), mode='w') as f:
			f.write(str(accuracy))
		if os.system('kaggle competitions submit -c uclacs145fall2019 -m "auto submission with accuracy {1}" -f "{0}"'.format(os.path.join(DATA_FOLDER, 'submit.csv'), accuracy)) != 0:
			print("Unable to submit dataset through kaggle API. Did you install the API and configure your API key properly?", file=sys.stderr)


DATA_FOLDER = os.path.normpath(os.path.dirname(os.path.realpath(__file__)) + "/../data")
ALL_GENRES = sorted(['Action', 'Adventure', 'Animation', 'Children', 'Comedy', 'Crime', 'Documentary', 'Drama', 'Fantasy', 'Film-Noir', 'Horror', 'IMAX', 'Musical', 'Mystery', 'Romance', 'Sci-Fi', 'Thriller', 'War', 'Western'])
MAX_ROWS = 0
FIRST_USERS = None

if __name__ == "__main__":
	main()
