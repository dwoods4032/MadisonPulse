// Hand-picked dinner, show, bar and late-night spots used to build a plan.
// Checked against 2025-2026 closing roundups on 2026-10-26: removed Short Stack (closed Jan 2025)
// and Jolly Bob's (closed Dec 2014). Ian's hours from ianspizza.com; Tornado and Greenbush from
// Madison Magazine and Table Journey listings.
// hrs = opening windows for late-night stops: [[days (0 = Mon), open, close], ...]; close past
//       midnight is written as 24:00+ (26:30 = 2:30 am). hrs:null = hours unconfirmed, left out of plans.
// tav = a tavern or brewpub (left out when the group isn't drinking).
// p = rough per-person spend with beer-level drinks. c = known for cocktails. g = roomy, good for groups. t = tiny room.
window.SPOTS = [
  {n:"The Old Fashioned",k:"dinner",a:"downtown",p:30,v:["classic","date"],c:1,w:"Capitol Square",d:"Wisconsin supper-club food. Get the cheese curds and a brandy Old Fashioned."},
  {n:"Tornado Steakhouse",k:"dinner",a:"downtown",p:60,v:["date","classic"],c:1,w:"Near the Capitol",d:"Old-school steakhouse with a proper martini. Pricey at dinner."},
  {n:"Weary Traveler Freehouse",tav:1,k:"dinner",a:"east",p:22,v:["chill","classic"],g:1,w:"1201 Williamson St",d:"Laid-back Willy Street pub with a globally inspired menu."},
  {n:"Villa Tap",tav:1,k:"dinner",a:"north",p:20,v:["dive","classic"],g:1,w:"2302 Packers Ave",d:"North-side tavern since 1978. Strong Friday fish fry, local beer."},
  {n:"Great Dane Pub & Brewing",tav:1,k:"dinner",a:"downtown",p:25,v:["chill","classic"],g:1,w:"123 E Doty St",d:"Brewpub with house beers and a big menu. Easy group pick."},
  {n:"Ian's Pizza",k:"dinner",a:"downtown",p:10,v:["cheap","chill"],g:1,w:"100 State St",d:"Big New York-style slices with wild toppings like mac and cheese."},
  {n:"High Noon Saloon",k:"show",a:"east",p:18,v:["music"],g:1,w:"701 E Washington Ave",d:"Mid-size room for touring and local bands."},
  {n:"The Rigby Pub",k:"show",a:"downtown",p:8,v:["music","cheap"],g:1,w:"119 E Main St",d:"Pub on the Square that books local acts. Often low or no cover."},
  {n:"Barrymore Theatre",k:"show",a:"east",p:30,v:["music","date"],g:1,w:"Atwood Ave",d:"1929 theater hosting music, comedy and film in the SASY neighborhood."},
  {n:"North Street Cabaret",k:"show",a:"north",p:15,v:["music","chill"],t:1,w:"North St",d:"Small room dedicated to roots music."},
  {n:"Majestic Theatre",k:"show",a:"downtown",p:35,v:["music"],g:1,w:"115 King St",d:"Historic downtown venue for bigger touring shows."},
  {n:"Ideal Bar",k:"bar",a:"east",p:12,v:["dive","cheap"],w:"1968 Atwood Ave",d:"Pinball and a jukebox. Start of the classic Atwood dive crawl."},
  {n:"Woody & Anne's",k:"bar",a:"east",p:12,v:["dive","cheap"],t:1,w:"2236 Winnebago St",d:"Tiny east-side dive with a 22-foot vintage shuffleboard table."},
  {n:"Wilson's Bar & Grill",k:"bar",a:"east",p:15,v:["chill","classic"],g:1,w:"2144 Atwood Ave",d:"Neighborhood spot that's good for watching a game."},
  {n:"Le Tigre Lounge",k:"bar",a:"west",p:12,v:["dive","cheap"],w:"1328 S Midvale Blvd",d:"West-side dive covered in tiger decor. One of a kind."},
  {n:"Crystal Corner Bar",k:"bar",a:"east",p:15,v:["music","classic"],g:1,w:"1302 Williamson St",d:"Big Willy Street bar with live music. Good last stop."},
  {n:"The Robin Room",k:"bar",a:"east",p:30,v:["date"],c:1,t:1,w:"Williamson St",d:"Small retro cocktail bar with serious mixology."},
  {n:"Mickey's Tavern",k:"bar",a:"east",p:15,v:["dive","chill"],g:1,w:"Williamson St",d:"Willy Street staple with a nostalgic, friendly feel."},
  {n:"Paul's Club",k:"bar",a:"downtown",p:14,v:["dive","chill"],w:"Downtown",d:"Decades-old downtown dive with a mixed crowd of students and regulars."},
  {n:"Genna's Lounge",k:"bar",a:"downtown",p:16,v:["chill","classic"],c:1,t:1,w:"Capitol Square",d:"Narrow, busy bar right on the Square with a solid cocktail list."},
  {n:"Tornado late-night menu",hrs:[[[4,5],"22:00","24:00"]],k:"late",a:"downtown",p:16,v:["date","classic"],w:"Near the Capitol",d:"Fridays and Saturdays, 10 pm to midnight: steak-house food at a fraction of dinner prices."},
  {n:"Ian's Pizza slice",hrs:[[[3],"11:00","26:00"],[[4,5],"11:00","26:30"],[[6,0,1,2],"11:00","22:00"]],k:"late",a:"downtown",p:6,v:["cheap"],w:"100 State St",d:"The bar-close slice. Open until 2 am Thursday and 2:30 am Friday and Saturday."},
  {n:"Jin's Chicken & Fish",hrs:null,k:"late",a:"downtown",p:9,v:["cheap"],w:"Library Mall cart",d:"Campus food cart that's a bar-time classic. Expect a line."},
  {n:"Greenbush Bakery",hrs:[[[0,1,2,3,4,5,6],"06:00","23:00"]],k:"late",a:"west",p:4,v:["cheap"],w:"Regent St",d:"Cheap donuts until 11 pm. The maple glazed is the move."}
];
