# Real-world speech: Indian-accented English

Generated 2026-10-06 11:56 · 13 minutes of [Svarah](https://huggingface.co/datasets/ai4bharat/Svarah) (AI4Bharat, CC BY 4.0) from 16 speakers, joined into 16 recordings of about 40 seconds, plus 10 own recordings.

Word error rate counts words only; hesitation sounds (*um, uh*) are left out because dataset transcripts don't write them. *Time per minute* is how long speech-to-text took for one minute of speech on this laptop's 12 CPU threads, averaged over the whole run; *vs small.en* is how many times longer than the app's current model that is. Both cover transcription only, not the rest of the analysis, and are rough: the laptop has mixed fast and slow cores and was not otherwise idle during the run.

| Model | Svarah WER | Own recordings WER | Time per minute | vs small.en | Download |
|---|---|---|---|---|---|
| small.en | 14.3% | 29.8% | 30 s | 1.0x | 0.5 GB |
| distil-large-v3.5 | 9.3% | 23.3% | 58 s | 2.0x | 1.5 GB |
| large-v3-turbo | 7.9% | 19.3% | 51 s | 1.7x | 1.6 GB |
| small.en (no filler prompt) | 10.5% | 28.4% | 12 s | 0.4x | 0.5 GB |

## By the speaker's first language (large-v3-turbo)

| Group | WER | Words |
|---|---|---|
| Tamil | 5.6% | 215 |
| Bodo | 7.6% | 144 |
| Urdu | 10.5% | 124 |
| Assamese | 0.9% | 115 |
| Hindi | 20.2% | 109 |
| Gujarati | 2.0% | 101 |
| Konkani | 7.3% | 96 |
| Kannada | 5.4% | 93 |
| Maithili | 12.2% | 90 |
| Punjabi | 2.3% | 88 |
| Bengali | 15.1% | 86 |
| Odia | 14.5% | 69 |

## Examples of mistakes

**small.en**

- said: *It has its own set of alphabets and letters Can you tell me whether the UPI transaction to Wahida is successful? In 1923, he brought out Maharashtra Dharma, Bird Kerala with an opposition team so it helps an individual to challenge themselves to perform better in that team and also strive for excellence I have not used a ride-sharing service to book a trip in a foreign country Wow People can actually manage to play them and it's a lot of fun English language is different from regional dialects. Tree Help Andhra Pradesh the change in season. For example, it is extremely cold during the winters and is extremely hot during the summer; so this shift*  
  heard: *It has its own set of alphabets and letters. Can you tell me whether the UPI transaction to Vahida is successful? in 1923, He brought out Maharashtrav dharma. with an opposition team. So it helps an individual to challenge themselves to perform better in that team and also strive for excellence. It has its own set of alphabets and letters. Wow! People can actually manage to play them and it's a lot of fun. English language is different, uh, from regional dialects. Three! Help! Andhra Pradesh, the change in season. For example, it is extremely cold during the winters and is extremely hot during the summer. So this shift.*
- said: *How much money do I have in my Capital Small Finance Bank bank account? For registered application ID MK201839611100749221 Down Eight Rate my order of 5 packs Godrej Aer Power Pocket Bathroom Air Fragrance as 5 stars Eight Despite a defeat of Ladakh by the Mughals, who had already annexed Kashmir and Baltistan, Ladakh retained its independence. Jump and date of birth 9-2-2020 Godrej Aer Power Pocket Bathroom Right*  
  heard: *How much money do I have in my capital small finance bank bank account? For registered application ID MK201839611100749221. Down. 8. Rate my order of 5 cash go to air powered pocket bathroom air fragrance as 5 cards. 8. Despite a defeat of Ladakh by the Mughals, who had already annexed Kashmir and Baltistan, Ladakh returned its independence. Jump. And date of birth 9 to 2020. Good is air powered pocket bathroom. Right.*
- said: *Are Pooja items available? 8th of August 1992, 27th of May 1997, 9th of January 2002, 2nd of June 1987, 2nd of December 2018. start radio Four Up Time Please tell me about 3 years return of Atal Pension Yojana Savings Scheme On what temperature do you bake a potato All these falls are located in the Western Ghats. During his reign, the Marwari horse was introduced, becoming Shah Jahan's favorite, and various Mughal cannons were mass-produced in the Jaigarh Fort.*  
  heard: *Are puja items available? 8th of August 1992. 27th of May 1997, 9th of January 2002, 2nd of June 1987, 2nd of December 2018. Start radio. Please tell me about it. Are puja items available? What temperature do you bake a potato? All these folds are located in the Western Ghats. During his reign, the Marwari horse was introduced, becoming Shah Jaha's favorite, and various Mughal cannons were mass -produced in the Jaigarh fort.*

**distil-large-v3.5**

- said: *It was a capital of Raj, Dharbhanga, an estate established in the 16th century. Chandrashekhar Jha special And Bagia is dumplings of rice flour. It is of two types, Doodh Bagia and Gudh Bagia. And then there is Nalanda With all these we celebrate important life events and milestones These are made with different kind of ingredients. In North Bihar, there is a lot of flooding, And Taruah is something in which any vegetable is fried or some of the leaves like there is one leaf called known as Tilkor.*  
  heard: *It was a capital of Raja, Durbhanga, an estate established in the 16th century. Chandrasekharja. Special and Bhagya. Bhagya is, you know, dumplings of rice flour. It is of two types, dood Bhagya and good Bhagya. And then there is Nalanda. With all these we celebrate important life events and milestones. These are made with different kind of ingredients in North Bihar there is a lot of flooding and Tarua is something in which any vegetable is fried or some of the leaves like there is one leaf called known as Thilkur*
- said: *The fee will vary depending on your country and state. And yes, if I'm asked for any specific goals or themes, And that was my inspiration. My inspiration for my photography was the, While there are many handiworks or craft works, handmade craft works that are available at lower Right He, at one point of time in his life, is my very always go-to, might be called a remedial Four So that was my inspiration. Puja and Kali Puja, he used to take such amazing snaps.*  
  heard: *the fee will vary depending on your country and state and yes if you if i'm asked for any specific goals or themes and that was my inspiration my inspiration for my photography was the there are while there are many uh handi works or craft works handmade craft words that are available at lower right um he at one point of time in his life is my very always a go -to might be called a remedial uh for so that was my inspiration at allah puja and kali puja he used to take such amazing snaps*
- said: *So, um the reason I chose this field is, uh mostly curiosity. I was, like, always taking things apart as a child. Hmm, my parents were not always happy about that.*  
  heard: *So, the reason I choose this to be curious, mostly curiosity. I was like always taking things about as a child. My parents were always not very good.*

**large-v3-turbo**

- said: *I mean, you know Ganesh Utsav, which is the Ganpati festival, Five named A Woman of No Importance by Oscar Wilde. And the quote is that every saint has a past and every sinner has a future to keep them alive, and yeah, it is working because we do have language-specific channels the disparities between communities. What are the items with offer from Pooja items ? and autopay a fourth of it every month for the whole year. Transfer Rs. 10000 amount to Zooni to the number of districts that make up a state, And the quote is that every saint has a past and every sinner has a future.*  
  heard: *I mean, um, you know, Ganesh Utsaf, which is the Ganpati festival. Five, named A Woman of No Importance by Oscar Wilde. And the quote is that every saint has a past and every sinner has a few to keep them alive. And, yeah, it is working because we do have language -specific channels, the disparities between communities. So, what are the items with offer from Pooja items? And auto -pay a fourth of it every month for the whole year. Transfer rupees 10 ,000 amount to Zuni to the number of districts that make up a state. And the quote is that every saint has a past and every sinner has a future. This is the number of districts that make up a state.*
- said: *The fee will vary depending on your country and state. And yes, if I'm asked for any specific goals or themes, And that was my inspiration. My inspiration for my photography was the, While there are many handiworks or craft works, handmade craft works that are available at lower Right He, at one point of time in his life, is my very always go-to, might be called a remedial Four So that was my inspiration. Puja and Kali Puja, he used to take such amazing snaps.*  
  heard: *The fee will vary depending on your country and state. And yes, if, uh, you, if I'm asked for any specific goals or themes. And, uh, that was my inspiration. My, uh, inspiration for my photography was the, there are, while there are many, uh, handiworks or craftworks, handmade craftworks that are available at lower. Right! Um, he, at one point of time in his life, um, is my very, uh, always, uh, go -to, uh, might be called a remedial, uh, for. So, that was my inspiration. I am Puja and Kali Puja. He used to take such amazing snaps.*
- said: *So, um the reason I chose this field is, uh mostly curiosity. I was, like, always taking things apart as a child. Hmm, my parents were not always happy about that.*  
  heard: *So, um, the reason I chose these three videos is, uh, mostly curiosity. I was, like, always thinking things about as a child. Um, my parents were always not happy about it.*
