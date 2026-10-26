// Hand-picked dinner, show, bar and late-night spots used to build a plan.
// tav = a tavern or brewpub (left out when the group isn't drinking).
// p = rough per-person spend with beer-level drinks. c = known for cocktails. g = roomy, good for groups. t = tiny room.
window.SPOTS = [
  {n:"The Old Fashioned",k:"dinner",a:"downtown",p:30,v:["classic","date"],c:1,w:"Capitol Square",d:"Wisconsin supper-club food. Get the cheese curds and a brandy Old Fashioned."},
  {n:"Tornado Steakhouse",k:"dinner",a:"downtown",p:60,v:["date","classic"],c:1,w:"Near the Capitol",d:"Old-school steakhouse with a proper martini. Pricey at dinner."},
  {n:"Weary Traveler Freehouse",tav:1,k:"dinner",a:"east",p:22,v:["chill","classic"],g:1,w:"1201 Williamson St",d:"Laid-back Willy Street pub with a globally inspired menu."},
  {n:"Villa Tap",tav:1,k:"dinner",a:"north",p:20,v:["dive","classic"],g:1,w:"2302 Packers Ave",d:"North-side tavern since 1978. Strong Friday fish fry, local beer."},
  {n:"Great Dane Pub & Brewing",tav:1,k:"dinner",a:"downtown",p:25,v:["chill","classic"],g:1,w:"123 E Doty St",d:"Brewpub with house beers and a big menu. Easy group pick."},
  {n:"Ian's Pizza",k:"dinner",a:"downtown",p:10,v:["cheap","chill"],g:1,w:"State St",d:"Big New York-style slices with wild toppings like mac and cheese."},
  {n:"High Noon Saloon",k:"show",a:"east",p:18,v:["music"],g:1,w:"701 E Washington Ave",d:"Mid-size room for touring and local bands."},
  {n:"The Rigby Pub",k:"show",a:"downtown",p:8,v:["music","cheap"],g:1,w:"119 E Main St",d:"Pub on the Square that books local acts. Often low or no cover."},
  {n:"Barrymore Theatre",k:"show",a:"east",p:30,v:["music","date"],g:1,w:"Atwood Ave",d:"1929 theater hosting music, comedy and film in the SASY neighborhood."},
  {n:"North Street Cabaret",k:"show",a:"north",p:15,v:["music","chill"],t:1,w:"North St",d:"Small room dedicated to roots music."},
  {n:"Majestic Theatre",k:"show",a:"downtown",p:35,v:["music"],g:1,w:"115 King St",d:"Historic downtown venue for bigger touring shows."},
  {n:"Ideal Bar",k:"bar",a:"east",p:12,v:["dive","cheap"],w:"1968 Atwood Ave",d:"Pinball and a jukebox. Start of the classic Atwood dive crawl."},
  {n:"Woody & Anne's",k:"bar",a:"east",p:12,v:["dive","cheap"],t:1,w:"2236 Winnebago St",d:"Tiny east-side dive with a 22-foot vintage shuffleboard table."},
  {n:"Wilson's Bar & Grill",k:"bar",a:"east",p:15,v:["chill","classic"],g:1,w:"2144 Atwood Ave",d:"Neighborhood spot that's good for watching a game."},
  {n:"Le Tigre Lounge",k:"bar",a:"west",p:12,v:["dive","cheap"],w:"1328 S Midvale Blvd",d:"West-side dive covered in tiger decor. One of a kind."},
  {n:"Jolly Bob's",k:"bar",a:"east",p:20,v:["chill","date"],c:1,w:"1210 Williamson St",d:"Caribbean-themed bar known for frozen rum drinks."},
  {n:"Crystal Corner Bar",k:"bar",a:"east",p:15,v:["music","classic"],g:1,w:"1302 Williamson St",d:"Big Willy Street bar with live music. Good last stop."},
  {n:"The Robin Room",k:"bar",a:"east",p:30,v:["date"],c:1,t:1,w:"Williamson St",d:"Small retro cocktail bar with serious mixology."},
  {n:"Mickey's Tavern",k:"bar",a:"east",p:15,v:["dive","chill"],g:1,w:"Williamson St",d:"Willy Street staple with a nostalgic, friendly feel."},
  {n:"Paul's Club",k:"bar",a:"downtown",p:14,v:["dive","chill"],w:"Downtown",d:"Decades-old downtown dive with a mixed crowd of students and regulars."},
  {n:"Genna's Lounge",k:"bar",a:"downtown",p:16,v:["chill","classic"],c:1,t:1,w:"Capitol Square",d:"Narrow, busy bar right on the Square with a solid cocktail list."},
  {n:"Tornado late-night menu",k:"late",a:"downtown",p:16,v:["date","classic"],w:"Near the Capitol",d:"From 10 pm, steak-house food at a fraction of dinner prices."},
  {n:"Ian's Pizza slice",k:"late",a:"downtown",p:6,v:["cheap"],w:"State St",d:"The bar-close slice. Open late."},
  {n:"Jin's Chicken & Fish",k:"late",a:"downtown",p:9,v:["cheap"],w:"Library Mall cart",d:"Campus food cart that's a bar-time classic. Expect a line."},
  {n:"Short Stack Eatery",k:"late",a:"east",p:14,v:["chill","cheap"],w:"Johnson St",d:"Pancakes and breakfast late. Check current hours."},
  {n:"Greenbush Bakery",k:"late",a:"west",p:4,v:["cheap"],w:"Regent St",d:"Cheap donuts. The maple glazed is the move."}
];
