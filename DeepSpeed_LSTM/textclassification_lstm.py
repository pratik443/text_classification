# -*- coding: utf-8 -*-
"""TextClassification_LSTM.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1g0sp536emr6VIws637kPpj_fHGv_D_i3
"""

import numpy as np 
import pandas as pd
import matplotlib.pyplot as plt
import re
import nltk
from nltk.stem import WordNetLemmatizer
from nltk.corpus import stopwords
from sklearn.model_selection import train_test_split
from nltk.tokenize import word_tokenize
import matplotlib.pyplot as plt 
import gensim
from gensim.utils import simple_preprocess
from gensim.parsing.porter import PorterStemmer
from gensim.models import Word2Vec

import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torch

import argparse
import deepspeed

from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, utils
from sklearn.metrics import classification_report

nltk.download('punkt')
nltk.download('wordnet')
nltk.download('stopwords')

def add_argument():
    parser=argparse.ArgumentParser(description='CIFAR')

    parser.add_argument('--with_cuda', default=False, action='store_true',
                        help='use CPU in case there\'s no GPU support')

    parser.add_argument('--use_ema', default=False, action='store_true',
                        help='whether use exponential moving average')

    parser.add_argument('-b', '--batch_size', default=1, type=int,
                        help='mini-batch size (default: 32)')

    parser.add_argument('-e', '--epochs', default=30, type=int,
                        help='number of total epochs (default: 30)')
    
    parser.add_argument('--local_rank', type=int, default=-1,
                    help='local rank passed from distributed launcher')

    parser = deepspeed.add_config_arguments(parser)

    args = parser.parse_args()

    return args

#stripping HTML tags
def striphtml(data):
    p = re.compile(r'<.*?>')
    return p.sub('', data)

# cleaning the text
def clean_text(text, max_sen_len=50):
    text = striphtml(text) 
    text = re.sub("[^a-zA-Z]", " ", text)
    text = text.lower()
    
    # tokenizing
    text = nltk.word_tokenize(text)
    
    # lemmatizing
    lma = WordNetLemmatizer()
    text = [lma.lemmatize(word) for word in text]
    
    # stop word removal
    stp = stopwords.words('english')
    text = [word for word in text if word not in stp]

    text = " ".join(text)

    return text

def contractions(s):
    s = re.sub(r"won???t", "will not",s)
    s = re.sub(r"would???t", "would not",s)
    s = re.sub(r"could???t", "could not",s)
    s = re.sub(r"\???d", " would",s)
    s = re.sub(r"can\???t", "can not",s)
    s = re.sub(r"n\???t", " not", s)
    s= re.sub(r"\???re", " are", s)
    s = re.sub(r"\???s", " is", s)
    s = re.sub(r"\???ll", " will", s)
    s = re.sub(r"\???t", " not", s)
    s = re.sub(r"\???ve", " have", s)
    s = re.sub(r"\???m", " am", s)
    return s

def change_label(label):
    if label == "c152":
        return 0
    elif label == "c153":
        return 1
    elif label == "c154":
        return 2
    elif label == "c155":
        return 3
    elif label == "c156":
        return 4
    elif label == "c157":
        return 5

        

# function to load word2vec model
def make_word2vec_model(data, padding=True, sg=1, min_count=1, size=100, workers=3, window=3):
    if  padding:
        temp_df = pd.Series(data['stemmed_tokens']).values
        temp_df = list(temp_df)
        temp_df.append(['pad'])
        word2vec_file = OUTPUT_FOLDER + 'word2vec_' + str(size) + '_PAD.model'
    else:
        temp_df = data['stemmed_tokens']
        word2vec_file = OUTPUT_FOLDER + 'word2vec_' + str(size) + '.model'

    w2v_model = Word2Vec(temp_df, min_count = min_count, size = size, workers = workers, window = window, sg = sg)

    w2v_model.save(word2vec_file)
    return w2v_model, word2vec_file

class LSTM(torch.nn.Module) :
    def __init__(self, vocab_size, embedding_dim, hidden_dim,num_classes) :
        super(LSTM,self).__init__()
        self.embeddings = nn.Embedding(vocab_size, embedding_dim, padding_idx=0)
        self.lstm = nn.LSTM(embedding_dim, hidden_dim, batch_first=True)
        self.linear1 = nn.Linear(hidden_dim, 24)
        self.linear2 = nn.Linear(24, num_classes)

        self.dropout = nn.Dropout(0.4)
        # self.relu =  nn.ReLU()
        self.softmax = nn.Softmax(dim=1)

        
    def forward(self, x):
        x = self.embeddings(x)

        lstm_out, (ht, ct) = self.lstm(x)

        x = self.linear1(ht[-1])
        # x = self.relu(x)
        x = self.dropout(x)

        x = self.linear2(x)

        x = self.dropout(x)

        x = self.softmax(x)

        return x

class TextDataset(Dataset):
    def __init__(self, X, Y):
        self.X = X
        self.Y = Y

        assert (len(X)==len(Y))

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        text = self.X.iloc[idx]
        label = self.Y.iloc[idx]
        sample = {"text": text, "label": label}
        return sample

if __name__ == '__main__':
    # reading the data
    df = pd.read_csv('sample.csv', header = None)
    df.columns = ["labels", 1, 2, 3, 4, "text", 6, 7, 8, 9, 10, 11, 12] # changing labels

    # cleaning the text for further processing
    df['text'] = df['text'].astype(str).apply(lambda x:contractions(x))
    df['text'] = df['text'].astype(str).apply(lambda x:clean_text(x))
    # df["text"] = [clean_text(text) for text in df["text"].astype(str)]
    df["labels"] = np.array([change_label(label) for label in df["labels"]])
    data = df[['labels', 'text']].copy()
    data.dropna(inplace=True)

    # plotting the label distribution
    # plt.figure()
    # pd.value_counts(data['labels']).plot.bar(title="label distribution")
    # plt.xlabel("labels")
    # # plt.ylabel("No. of rows in df")
    # plt.show()

    # tokenizing the text the text column to get the new column 'tokenized_text'
    data['tokenized_text'] = [simple_preprocess(line, deacc=True) for line in data['text']] 

    # stemming the text to reduce it to its root words and save the new text in a new column 'stemmed_tokens'
    porter_stemmer = PorterStemmer()
    data['stemmed_tokens'] = [[porter_stemmer.stem(word) for word in tokens] for tokens in data['tokenized_text']]
    data['stemmed_tokens'] = data['stemmed_tokens'].apply(lambda x: " ".join(x))

    TRAINSIZE = int(0.8*len(data))

    trainset = TextDataset(data[:TRAINSIZE]['stemmed_tokens'], data[:TRAINSIZE]['labels'])
    testset = TextDataset(data[TRAINSIZE:]['stemmed_tokens'], data[TRAINSIZE:]['labels'])
    
    # main model block

    # # use cuda if present
    # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # print("Device available for running: ")
    # print(device)

    # set your output folder
    OUTPUT_FOLDER = './'

    # specify the size of the strings. Here 500 is used
    SIZE = 100
    WINDOW = 3
    MIN_COUNT = 1
    WORKERS = 3
    SG = 1
    NUM_EPOCHS = 12
    SAVE_EVERY = 5

    # load Word2vec model
    w2vmodel, word2vec_file = make_word2vec_model(data, padding=True, sg=SG, min_count=MIN_COUNT, size=SIZE, workers=WORKERS, window=WINDOW)

    #function to generate input tensor.
    max_sen_len = data.stemmed_tokens.map(len).max()
    padding_idx = w2vmodel.wv.vocab['pad'].index

    # number of labels to use, we will use all of them i,e. 6
    NUM_CLASSES = 6
    EMBEDDING_DIM = 3
    VOCAB_SIZE = len(w2vmodel.wv.vocab)
    HIDDEN_DIM = 2

    lstm_model = LSTM(vocab_size= VOCAB_SIZE,embedding_dim=EMBEDDING_DIM,hidden_dim=HIDDEN_DIM,num_classes=NUM_CLASSES) 
    loss_function = nn.CrossEntropyLoss()
    # optimizer = optim.Adam(cnn_model.parameters(), lr=0.001)
    

    parameters = filter(lambda p: p.requires_grad, lstm_model.parameters())
    args = add_argument()
    

    # Initialize DeepSpeed to use the following features
    # 1) Distributed model
    # 2) Distributed data loader
    # 3) DeepSpeed optimizer
    model_engine, optimizer, trainloader, _ = deepspeed.initialize(args=args, model=lstm_model, model_parameters=parameters, training_data=trainset)
    lstm_model.to(model_engine.device)

    def make_word2vec_vector_lstm(sentence):
        padded_X = [padding_idx for i in range(max_sen_len)]
        i = 0
        for word in sentence:
            if word not in w2vmodel.wv.vocab:
                padded_X[i] = 0
                print(word)
            else:
                padded_X[i] = w2vmodel.wv.vocab[word].index
            i += 1
        return padded_X

    def make_target(label):
        for x in range(NUM_CLASSES):
            if label == x:
                return x

    # open the file for writing loss
    loss_file_name = OUTPUT_FOLDER + 'lstm_class_big_loss_with_padding.csv'
    f = open(loss_file_name, 'w')
    f.write('iter, loss')
    f.write('\n')
    losses = []
    model_engine.train()

    for epoch in range(1, NUM_EPOCHS+1):
        print("Epoch" + str(epoch))
        train_loss = 0
        
        for step, batch in enumerate(trainloader):

            # Clearing the accumulated gradients
            model_engine.zero_grad()

            # Make the bag of words vector for stemmed tokens 
            bow_vec = batch['text'] 
            bow_vec = torch.tensor([make_word2vec_vector_lstm(vec) for vec in bow_vec], dtype=torch.long).to(model_engine.device)
            # print(bow_vec.shape)

            # Forward pass to get output
            probs = model_engine(bow_vec)

            # Get the target label
            target = batch['label'] 
            target = torch.tensor([make_target(x) for x in target], dtype=torch.long).to(model_engine.device)

            # Calculate Loss: softmax --> cross entropy loss
            loss = loss_function(probs, target)
            train_loss += loss.item()

            # Getting gradients w.r.t. parameters
            model_engine.backward(loss)

            # Updating parameters
            model_engine.step()
        
        print("Epoch ran :"+ str(epoch+1))
        f.write(str((epoch)) + "," + str(train_loss/len(trainset)))
        f.write('\n')
        train_loss = 0
    
        if (epoch%SAVE_EVERY==0):
            print('YO')
            model_engine.save_checkpoint(OUTPUT_FOLDER + 'lstm_big_model_' + str(EMBEDDING_DIM) + '_with_padding_epoch_{}.pth'.format(epoch), tag=None, client_state={}, save_latest=True)
        # print(OUTPUT_FOLDER + 'cnn_big_model_' + str(EMBEDDING_SIZE) + '_with_padding.pth')
        # torch.save(model_engine, OUTPUT_FOLDER + 'cnn_big_model_' + str(EMBEDDING_SIZE) + '_with_padding.pth')

        print("Input vector")
        print(bow_vec.cpu().numpy())
        print("Probs")
        print(probs)
        print(torch.argmax(probs, dim=1).cpu().numpy()[0])

    f.close()

    # testing
    bow_lstm_predictions = []
    original_lables_lstm_bow = []

    model_engine.eval()
    loss_df = pd.read_csv(OUTPUT_FOLDER + 'lstm_class_big_loss_with_padding.csv')

    with torch.no_grad():
        for row in testset:
            bow_vec = torch.tensor(make_word2vec_vector_lstm(row['text']), dtype=torch.long).to(model_engine.device).unsqueeze(0)
            probs = model_engine(bow_vec)
            _, predicted = torch.max(probs.data, 1)
            bow_lstm_predictions.append(predicted.cpu().numpy()[0])
            original_lables_lstm_bow.append(make_target(row['label']))

        print(classification_report(original_lables_lstm_bow,bow_lstm_predictions))
        loss_file_name = OUTPUT_FOLDER + 'lstm_class_big_loss_with_padding.csv'
        loss_df = pd.read_csv(loss_file_name)
        print(loss_df.columns)

        #plotting the loss graph
        plt_500_padding_30_epochs = loss_df[' loss'].plot()
        fig = plt_500_padding_30_epochs.get_figure()