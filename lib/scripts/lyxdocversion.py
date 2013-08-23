#!/usr/bin/env python
# -*- coding: utf-8 -*-
# c-basic-offset: 3; tab-width: 3; indent-tabs-mode: t
# vi: set shiftwidth=3 tabstop=3 noexpandtab:
# :indentSize=3:tabSize=3:noTabs=false:

import os
import mmap
import argparse
import logging
import time
import copy
import re
import xml.etree.ElementTree as ET
import xml.dom.minidom as DOM
import subprocess
import tempfile

class LyXdocParser (object) :
	class _LyX_FileParserState (object) :
		def __init__ (self) :
			self.InHeader         = False
			self.CurrentBranch    = ''
			self.InIncludeonly    = False
			self.InBody           = False
			self.CurrentInclude   = ''
			self.Inset            = list()
			self.CommandInset     = ''
			self.IncludeType      = ''
			self.IgnoreLevel      = 0
			self.InactiveBranches = set()
			self.Includeonlyused  = False

	def __init__ (self, File, LyXdocRoot = None) :
		self._File         = File
		self._FileNameFull = self._getFullPath(self._File.name)
		self._LyXdocRoot   = LyXdocRoot if LyXdocRoot is not None else ET.Element("LyXdoc")

	def _getFullPath (self, FileName) :
		FullPath = os.path.abspath(os.path.basename(FileName)) if os.path.isabs(FileName) else os.path.abspath(FileName)	
		if not os.path.isabs(FullPath) :
			logging.error('Error determining full file name for file "{0}"'.format(File))
			return unicode(FileName)
		else :
			return unicode(FullPath)

	def parseTree (self, InactiveMasterBranches = None) :
		'''
		A LyX file parser for external material.
		This parser reterns an xml.etree.ElementTree

		This parser does not evaluate LaTeX macros and therefore does not recognize constructs like:
		1) \graphicspath{}
		2) \DeclareGraphicsExtensions{}
		3) Material included in ERT
		4) File names that are determined by LaTeX macros
		5) ...
		'''
		FileData  = mmap.mmap(self._File.fileno(), 0, access = mmap.ACCESS_READ)
		State     = self._LyX_FileParserState()
		Root      = self._LyXdocRoot
		Branches  = ET.SubElement(Root, "branches")
		Children  = ET.SubElement(Root, "children")
		Materials = ET.SubElement(Root, "materials")

		Root.set('filename', self._FileNameFull)
	
		if InactiveMasterBranches :
			State.InactiveBranches |= InactiveMasterBranches

		for LineNumber, Line in enumerate(iter(FileData.readline, '')) :
			if len(Line) < 9 :
				continue

			NextState = copy.deepcopy(State)

			if Line.endswith('\r') :
				Line = Line[:-1] + '\n'

			if Line.endswith('\r\n') :
				Line = Line[:-2] + '\n'
		
			if State.InBody :
				if '\\end_body' in Line :
					NextState.InHeader = False
					NextState.InBody   = False
					State = NextState; continue

				if '\\end_inset' in Line :
					if State.Inset[-1] in {'CommandInset'} :
						NextState.CommandInset = ''
						NextState.IncludeType  = ''
					elif State.Inset[-1] in {'Note', 'Branch'} and State.IgnoreLevel == len(State.Inset) :
						NextState.IgnoreLevel = 0
						logging.debug("{0: >7}: {1}end   {2}{3}".format(LineNumber + 1, len(State.Inset) * '\t', State.Inset[-1], " (ignored)" if State.IgnoreLevel > 0 else ""))
					NextState.Inset.pop()
					State = NextState; continue

				'''
				This block handles the extraction of file names for CommandInset insets
				The actual type of inset in this case is determined by the 'LatexCommand' command inside the inset
				'''
				if len(State.CommandInset) > 0 and State.IgnoreLevel == 0 :
					if State.CommandInset in {'include'} :
						if len(State.IncludeType) > 0 and State.IncludeType in {'include', 'input'} :
							SearchResult = re.search(r'^filename\s\"(.+?)\"', Line)
							if SearchResult :
								FileName, FileExtension = os.path.splitext(SearchResult.group(1))
								FilePath  = self._getFullPath(FileName + FileExtension)
								if FileExtension.lower() in {'.lyx'} :
									if State.Includeonlyused == False :
										Child = ET.SubElement(Children, "child")
										Child.set('filename', FilePath)
										with open(FilePath) as File :
											ChildParser = LyXdocParser(File, Child)
											ChildParser.parseTree(State.InactiveBranches)
								else :
									Material = ET.SubElement(Materials, "material")
									Material.set('filename', FilePath)								
						elif len(State.IncludeType) > 0 and State.IncludeType in {'verbatiminput', 'lstinputlisting'} :
							SearchResult = re.search(r'^filename\s\"(.+?)\"', Line)
							if SearchResult :
								FilePath = self._getFullPath(SearchResult.group(1))
								Material = ET.SubElement(Materials, "material")
								Material.set('filename', FilePath)
						else :
							SearchResult = re.search(r'^LatexCommand\s(.+?)$', Line)
							if SearchResult :
								IncludeType = SearchResult.group(1)
								NextState.IncludeType = IncludeType
					elif State.CommandInset in {'bibtex'} :
						SearchResult = re.search(r'^bibfiles\s\"(.+?)\"$', Line)
						if SearchResult :
							Files = SearchResult.group(1).split(',')
							for File in Files :
								FileName, FileExtension = os.path.splitext(File)
								FilePath = self._getFullPath(FileName + '.bib')
								Bibfile = ET.SubElement(Materials, "material")
								Bibfile.set('filename', FilePath)
					State = NextState; continue

				'''
				This block handles the extraction of file names for Graphics and External insets
				'''
				if len(State.Inset) > 0 and State.Inset[-1] in {'Graphics', 'External'} and State.IgnoreLevel == 0 :
					SearchResult = re.search(r'^\tfilename\s(.+?)$', Line)
					if SearchResult :
						FilePath = self._getFullPath(SearchResult.group(1))
						Material = ET.SubElement(Materials, "material")
						Material.set('filename', FilePath)
						continue

				'''
				The following code block determines if we should look for external material, child documents or bibliographies ...
			
				I think this has to be complicated because
				(a) of the file format and
				(b) we have to test for nested insets, comment insets (Note Comment), disabled branches and includeonly in the header
				'''
				SearchResult = re.search(r'^\\begin_inset\s(.+?)\s', Line)
				if SearchResult :
					InsetType = SearchResult.group(1)
					NextState.Inset.append(InsetType) # Increase the inset level for each "\begin_inset" because the "\end_inset" command does not tell us which inset it ends.
					if InsetType in {'Graphics', 'External'} :
						logging.debug("{0: >7}: {1}begin {2}{3}".format(LineNumber + 1, len(State.Inset) * '\t', InsetType, " (ignored)" if State.IgnoreLevel > 0 else ""))
					elif InsetType in {'CommandInset', 'Note', 'Branch'} :
						SearchResult = re.search(r'^\\begin_inset\s.+?\s(.+?)$', Line)
						if SearchResult :
							InsetArgument = SearchResult.group(1)
							if InsetType in {'CommandInset'} and InsetArgument in {'include', 'bibtex'}:
								NextState.CommandInset = InsetArgument
								logging.debug("{0: >7}: {1}{2} {3}{4}".format(LineNumber + 1, len(State.Inset) * '\t', InsetType, InsetArgument, " (ignored)" if State.IgnoreLevel > 0 else ""))
							elif InsetType in {'Note'} and InsetArgument in {'Comment'} :
								logging.debug("{0: >7}: {1}{2} {3}{4}".format(LineNumber + 1, len(State.Inset) * '\t', InsetType, InsetArgument, " (ignored)" if State.IgnoreLevel > 0 else ""))
								if State.IgnoreLevel == 0 :
									NextState.IgnoreLevel = len(State.Inset) + 1
							elif InsetType in {'Branch'} :
								logging.debug("{0: >7}: {1}{2} {3}{4}".format(LineNumber + 1, len(State.Inset) * '\t', InsetType, InsetArgument, " (ignored)" if State.IgnoreLevel > 0 else ""))
								if InsetArgument in State.InactiveBranches and State.IgnoreLevel == 0 :
									NextState.IgnoreLevel = len(State.Inset) + 1
						else :
							logging.error("{0: >7}: malformed {1} inset".format(LineNumber, InsetType))
					State = NextState; continue
			elif State.InHeader :
				if '\\end_header' in Line :
					NextState.InHeader = False
					NextState.InBody   = False
					State = NextState; continue

				SearchResult = re.search(r'^\\master\s(.+?)$', Line)
				if SearchResult :
					Root.set('master', self._getFullPath(SearchResult.group(1)))
					State = NextState; continue

				if '\\end_branch' in Line :
					# end of branch definition
					NextState.CurrentBranch = ''
					State = NextState; continue

				if len(State.CurrentBranch) > 0 :
					# in branch definition
					SearchResult = re.search(r'\\selected\s(\d)', Line)
					if SearchResult :
						if SearchResult.group(1) == '0' :
							for Branch in Branches.findall("./branch[@name='" + State.CurrentBranch + "']") :
								Branch.set('selected', "false")
						else :
							for Branch in Branches.findall("./branch[@name='" + State.CurrentBranch + "']") :
								Branch.set('selected', "true")
							NextState.InactiveBranches -= {State.CurrentBranch}
					
						State = NextState; continue
				else :
					# begin of branch definition
					SearchResult = re.search(r'^\\branch\s(.+?)$', Line)
					if SearchResult :
						BranchName = SearchResult.group(1)
						Branch     = ET.SubElement(Branches, "branch")
						Branch.set('name', BranchName)
						NextState.CurrentBranch = BranchName
						NextState.InactiveBranches |= {BranchName}
						State = NextState; continue

				if '\\end_includeonly' in Line :
					# end of includeonly
					NextState.InIncludeonly = False
					State = NextState; continue

				if State.InIncludeonly == True :
					# in includeonly - one file per line, all included child documents listed
					FilePath = self._getFullPath(Line.strip('\n'))
					Child = ET.SubElement(Children, "child")
					Child.set('filename', FilePath)
					with open(FilePath) as File :
						ChildParser = LyXdocParser(File, Child)
						ChildParser.parseTree(State.InactiveBranches)

					logging.debug("{0: >7}: includeonly file: {1}".format(LineNumber + 1, Line.strip('\n')))
					State = NextState; continue

				if '\\begin_includeonly' in Line :
					# begin of includeonly
					NextState.InIncludeonly   = True
					NextState.Includeonlyused = True
					State = NextState; continue

			else :
				if '\\begin_header' in Line :
					NextState.InHeader = True
					NextState.InBody   = False
				elif '\\begin_body' in Line :
					NextState.InHeader = False
					NextState.InBody   = True

			State = NextState

	def getPrettyXML (self) :
		XMLstring = ET.tostring(self._LyXdocRoot, encoding = 'utf-8')
		DOMobject = DOM.parseString(XMLstring)
		PrettyXML = DOMobject.toprettyxml(indent = '  ', encoding = 'utf-8')
		return PrettyXML

	def getElementTree (self) :
		Tree = ET.ElementTree(self._LyXdocRoot)
		return Tree

	def getRootElement (self) :
		RootElement = self._LyXdocRoot
		return RootElement

	def getRootDocument (self) :
		Root = self.getRootElement()
		RootDocument = Root.get('filename')
		return RootDocument

	def getChildDocuments (self) :
		Root = self.getRootElement()
		ChildDocuments = list()
		for ChildDocument in Root.findall('.//children/child') :
			ChildDocuments.append(ChildDocument.get('filename'))
		return ChildDocuments

	def getLyX_Documents (self) :
		LyX_Documents = list()
		LyX_Documents.append(self.getRootDocument())
		LyX_Documents += self.getChildDocuments()
		return LyX_Documents

	def getMaterials (self) :
		Materials = list()
		Root = self.getRootElement()
		for Material in Root.findall('.//materials/material') :
			Materials.append(Material.get('filename'))
		return Materials

	def getAllFiles (self) :
		Files = list()
		Files += self.getLyX_Documents()
		Files += self.getMaterials()
		return Files

	def getLongestCommonPath (self) :
		RootDocument = self.getRootDocument()
		Filenames = self.getAllFiles()
		LongestCommonPath = min(len(Filename) for Filename in Filenames)
		Comparisons = list()
		for Filename in Filenames :
			for i in range(LongestCommonPath) :
				Comparison = ord(RootDocument[i]) ^ ord(Filename[i])
				if not Comparison == 0 :
					LongestCommonPath = min(LongestCommonPath, i)
					break
		return RootDocument[:LongestCommonPath]

class LyXdocSVNquery (object) :
	"""
	A wrapper for SVN that requests SVN meta-information about all documents
	in a LyX document tree.
	"""

	_Documents = list()
	_Revisions = list()
	_Authors   = list()
	_Dates     = list()

	def __init__ (self, Documents) :
		self._Documents = Documents
	
	def _prettyprintXML (self, XML) :
		XML_String = ''.join(XML.splitlines())
		MyETree = ET.fromstring(XML_String)
		XML_String = ET.tostring(MyETree, encoding = 'utf-8')
		DOMobject = DOM.parseString(XML_String)
		PrettyXML = DOMobject.toprettyxml(indent = '  ', encoding = 'utf-8')
		return PrettyXML

	def runSVN (self) :
		for FileName in self._Documents :
			SVNcommand = 'svn info --non-interactive --xml "{0}"'.format(FileName)
			try :
				SVNinfoXML = subprocess.check_output(SVNcommand)
			except CalledProcessError as Exception :
				logging.warn('SVN exited with non-zero exit code {0}'.format(Exception.returncode))
			except :
				logging.error('SVN command failed: {0}'.format(SVNcommand))
			finally :
				MyDOM = DOM.parseString(SVNinfoXML)
				Commit = MyDOM.getElementsByTagName('commit')[0]
				Revision = int(Commit.getAttribute('revision'))
				self._Revisions.append(Revision)
				for CommitDetail in Commit.childNodes :
					if CommitDetail.nodeType == 1 :
						if CommitDetail.nodeName in ['author'] :
							self._Authors.append(CommitDetail.firstChild.nodeValue)
						if CommitDetail.nodeName in ['date'] :
							# date example: 2012-11-16T10:23:28.165183Z
							CommitTime = CommitDetail.firstChild.nodeValue[:19]
							CommitTime = time.strptime(CommitTime, '%Y-%m-%dT%H:%M:%S')
							self._Dates.append(CommitTime)

	def getRevisionData (self) : 
		LatestRevision = self._Revisions.index(max(self._Revisions))
		NewestRevision = unicode(self._Revisions[LatestRevision])
		NewestDate     = unicode(time.strftime('%Y-%m-%d',self._Dates[LatestRevision]))
		NewestTime     = unicode(time.strftime('%H:%M:%S',self._Dates[LatestRevision]))
		NewestAuthor   = self._Authors[LatestRevision]
		LatestRevisionData = {'revision': NewestRevision, 'date': NewestDate, 'time': NewestTime, 'author': NewestAuthor}
		return LatestRevisionData

"""
ChildDocuments = re.findall(PatternDoc, FileData)
for n, Match in enumerate(ChildDocuments) :
	print str(n) + ": " + Match
"""
def main():
	#       keep trailing zeros (fixed with msecs): v                  v make the message start at a fixed column
	logging.basicConfig(format='%(asctime)s,%(msecs).03d   %(levelname)-8s   %(message)s', datefmt='%Y-%m-%dT%H:%M:%S', level=logging.INFO)
	logging.Formatter.converter = time.gmtime

	MyArgumentParser = argparse.ArgumentParser(description = 'Returns the SVN revision of a LyX document including dependencies excluding the TeX environment.')
	MyArgumentParser.add_argument('-f', '--follow', dest = 'follow', action = 'store_true',
										 help = 'Follow master file refernce.')
	MyArgumentParser.add_argument('-o', '--out', dest = 'outfile', type=argparse.FileType('w'), nargs = '?',
										 help = 'Write a list of files used to determine the revision to %(dest)s.')
	MyArgumentParser.add_argument('file', type=argparse.FileType(),
										 help = 'The LyX document of which the revision data is requested.')
	ArgumentGroup = MyArgumentParser.add_argument_group('output arguments', 'Only one value is returned per run, i. e. you cannot request multiple values.')
	ArgumentGroup.add_argument('-r', '--revision', dest = 'revision', action = 'store_true',
									 help = 'Return the highest revision of the document (default).')
	ArgumentGroup.add_argument('-d', '--date', dest = 'date', action = 'store_true',
									 help = 'Return the date of the highest revision of the document.')
	ArgumentGroup.add_argument('-t', '--time', dest = 'time', action = 'store_true',
									 help = 'Return the time of the highest revision of the document.')
	ArgumentGroup.add_argument('-a', '--author', dest = 'author', action = 'store_true',
									 help = 'Return the author of the highest revision of the document.')

	Arguments = MyArgumentParser.parse_args()

	TheFile = Arguments.file
	MyLyXdocParser = LyXdocParser(TheFile)
	MyLyXdocParser.parseTree()

	MySVN_Query = LyXdocSVNquery(MyLyXdocParser.getAllFiles())
	MySVN_Query.runSVN()

	if Arguments.date == True :
		print MySVN_Query.getRevisionData()['date']
	elif Arguments.time == True :
		print MySVN_Query.getRevisionData()['time']
	elif Arguments.author == True :
		print MySVN_Query.getRevisionData()['author']
	else :
		print MySVN_Query.getRevisionData()['revision']
	
if __name__ == '__main__' :
	main()